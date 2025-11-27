# llrfgui_threadsafe.py
import sys
import os
import numpy as np
from PIL import Image

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap, QDoubleValidator
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QLineEdit, QLabel,
    QVBoxLayout, QHBoxLayout, QTabWidget, QFileDialog, QMessageBox,
    QSlider, QDialog, QPlainTextEdit, QGroupBox, QSizePolicy, QSpacerItem
)

import pyqtgraph as pg

# --- CONSTANTS ---
MAX_PULSE_TIME_US = 34.0
DEFAULT_IP = "192.168.0.109"
DEFAULT_USER = "root"
DEFAULT_PWD = "Jungle"
DEFAULT_MAX_AMP = "1000"

# --- STYLES (Estetica Migliorata) ---
GUI_STYLE = """
    QGroupBox {
        font-weight: bold;
        margin-top: 10px;
        border: 2px solid #555555;
        border-radius: 5px;
        padding-top: 15px;
    }
    QPushButton {
        padding: 5px;
        border-radius: 3px;
        /* Imposta uno sfondo predefinito per i pulsanti abilitati */
        background-color: #007BFF; 
        color: white;
    }
    QTabWidget::pane { 
        border: 1px solid #C4C4C3;
        background: white;
    }
    QLabel#StatusLabel {
        font-size: 14px;
        font-weight: bold;
        padding: 5px;
        border-radius: 3px;
        background-color: #222222;
        color: white; 
    }
    /* CORREZIONE VISIBILITÀ: Rende i widget non-input visibili. */
    QLineEdit {
        background-color: #F0F0F0;
        border: 1px solid #AAAAAA;
        padding: 3px;
        color: black; 
    }
    QLabel {
        color: black;
    }
    /* SOLUZIONE DEFINITIVA VISIBILITÀ PULSANTI DISABILITATI: 
       Forza uno stile visibile per i pulsanti disabilitati (come Load/Send all'inizio). */
    QPushButton:disabled {
        background-color: #E0E0E0; /* Grigio chiaro forzato */
        color: #A0A0A0; /* Testo grigio scuro forzato */
    }
    /* Sovrascrivi gli stili di connessione disabilitati per mantenerli grigi */
    QPushButton#btn_disconnect:disabled {
        background-color: #AAAAAA;
    }
"""

# ====================================================================
# MOCK CLASS (Solo per testing)
# ====================================================================
try:
    from LLRF import LLRFConnection
except ImportError:
    class LLRFConnection:
        def __init__(self, ip, user, pwd):
            pass
        def connect(self):
            import time; time.sleep(1.0) # Simulate connection time
            pass
        def close(self):
            pass
        def FF_Change_MaxAmp(self, max_amp):
            import time; time.sleep(0.3)
            pass
        def FF_Change_Interval(self, offset, duration):
            import time; time.sleep(0.5)
            pass
        def FF_Change_Phase(self, phase, update):
            import time; time.sleep(0.3)
            pass
        def Restore(self):
            import time; time.sleep(1.5)
            pass
        def Set_Arbitrary_Shape(self, wave, max_amp, init_t):
            import time; time.sleep(0.7)
            return "Waveform amplitude uploaded (1D)"
        def Set_Arbitrary_Shape_AndTime(self, amplitude, max_amp, t_start, t_end):
            import time; time.sleep(0.7)
            return "Waveform amplitude uploaded (2D)"
        def Set_Arbitrary_Phase(self, wave_phase, cent_phase, init_t):
            import time; time.sleep(0.7)
            return "Waveform phase uploaded (1D)"
        def Set_Arbitrary_Phase_AndTime(self, amplitude, cent_phase, t_start, t_end):
            import time; time.sleep(0.7)
            return "Waveform phase uploaded (2D)"

class LLRFWorker(QThread):
    """Esegue una funzione in un QThread e riporta via segnali."""
    finished = pyqtSignal(object)
    error = pyqtSignal(Exception)
    log = pyqtSignal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            res = self.func(*self.args, **self.kwargs)
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(e)
            self.log.emit(f"Worker error: {e}")


class LLRF_GUI(QWidget):
    log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        # --- State ---
        self.conn = None
        self.online = False
        self.original_wave = None
        self.loaded_wave = None
        self.original_wave_phase = None
        self.loaded_wave_phase = None
        self._slider_active = None
        self._active_workers = [] # Traccia i worker attivi
        
        # --- Setup ---
        self._setup_ui()
        self._connect_signals()
        self._update_global_state() # Chiama la funzione di stato globale

    # ====================================================================
    # UI CONSTRUCTION & STATE MANAGEMENT
    # ====================================================================

    def _set_working_state(self, is_working: bool):
        """Gestisce il cursore e i messaggi di log per l'attività in corso."""
        if is_working:
            app = QApplication.instance()
            if app:
                app.setOverrideCursor(Qt.WaitCursor)
            self.log(">>> Operation in progress. Please wait...")
        else:
            app = QApplication.instance()
            if app:
                app.restoreOverrideCursor()
            if len(self._active_workers) == 0:
                 self.log("<<< Operation finished.")
        
        # Chiama l'aggiornamento UI per riflettere lo stato (disabilitazione/abilitazione)
        self._update_ui_state()

    def _update_global_state(self):
        """Aggiorna lo stato globale in base al conteggio dei worker attivi."""
        is_working = len(self._active_workers) > 0
        self._set_working_state(is_working)

    def _update_ui_state(self):
        """Abilita/disabilita i widget in base a connessione e attività del worker."""
        is_working = len(self._active_workers) > 0
        
        # Widgets che richiedono una connessione E un'azione (Send, Set Amp/Phase/Interval, Restore)
        requires_conn_and_action = [
            self.btn_disconnect, self.btn_set_amp, self.btn_set_interval,
            self.btn_restore,  self.btn_send_wave,
            self.btn_send_wavephase, self.max_amp, self.offset,
            self.duration
        ]
        
        # Widgets che non richiedono connessione ma devono essere disabilitati da is_working
        # (Load/Refresh sono sempre attivi, a meno che non ci sia un worker in corso)
        non_conn_widgets_disabled_by_working = [
             self.btn_load_wave, self.btn_load_wavephase,
             self.btn_force_update_amp, self.btn_force_update_phase,
             self.tabs
        ]
        
        # 1. Gestione pulsanti di connessione
        self.btn_connect.setEnabled(not self.online and not is_working)
        self.btn_disconnect.setEnabled(self.online and not is_working)
        
        # 2. Aggiornamento estetico del pulsante e dello stato
        if self.online:
            self.btn_connect.setStyleSheet("background-color: #AAAAAA;")
            self.btn_disconnect.setStyleSheet("background-color: #FF5555; color: white; font-weight: bold;")
            self.status_label.setText("STATUS: CONNECTED")
            self.status_label.setStyleSheet("QLabel#StatusLabel {background-color: #00AA00;}")
        else:
            self.btn_connect.setStyleSheet("background-color: #00AA00; color: white; font-weight: bold;")
            self.btn_disconnect.setStyleSheet("background-color: #AAAAAA;")
            self.status_label.setText("STATUS: DISCONNECTED")
            self.status_label.setStyleSheet("QLabel#StatusLabel {background-color: #FF5555;}")

        # 3. Disabilita/Abilita i widget che richiedono connessione
        enabled_conn_action = self.online and not is_working
        for widget in requires_conn_and_action:
            widget.setEnabled(enabled_conn_action)
            
        # 4. Disabilita/Abilita i widget che non richiedono connessione
        enabled_non_conn = not is_working
        for widget in non_conn_widgets_disabled_by_working:
             widget.setEnabled(enabled_non_conn)


    def _setup_ui(self):
        self.setWindowTitle("LLRF Control Console")
        self.resize(1000, 750)
        self.setStyleSheet(GUI_STYLE)

        # Log Area (CREATO SUBITO)
        self.log_display = QPlainTextEdit()
        self.log_display.setReadOnly(True)
        # Correzione font per macOS/Compatibilità
        self.log_display.setStyleSheet("background:black; color:#0f0; padding:5px; font-family:'Menlo', 'Monaco', monospace, sans-serif;")
        self.log_display.setMaximumBlockCount(5000)
        self.log_display.setPlainText("LLRF GUI Ready")

        # Validators
        double_validator = QDoubleValidator()
        double_validator.setNotation(QDoubleValidator.StandardNotation)

        # --- Connection tab ---
        tab_conn = QWidget()
        l_conn = QVBoxLayout(tab_conn)
        
        # Connection Parameters Group
        conn_group = QGroupBox("1. Connection Parameters")
        l_conn_group = QVBoxLayout(conn_group)
        self.ip = QLineEdit(DEFAULT_IP)
        self.user = QLineEdit(DEFAULT_USER)
        self.pwd = QLineEdit(DEFAULT_PWD)
        
        for lbl, widget in [("IP Address", self.ip), ("Username", self.user), ("Password", self.pwd)]:
            h = QHBoxLayout()
            h.addWidget(QLabel(lbl))
            widget.setEchoMode(QLineEdit.Password) if lbl == "Password" else None
            h.addWidget(widget)
            l_conn_group.addLayout(h)
        
        # Connection Control Group
        btn_group = QGroupBox("2. Connection Control")
        h_btn = QHBoxLayout(btn_group)
        self.btn_connect = QPushButton("CONNECT")
        self.btn_disconnect = QPushButton("DISCONNECT")
        self.status_label = QLabel(alignment=Qt.AlignCenter) # CREATO QUI
        self.status_label.setObjectName("StatusLabel")
        
        h_btn.addWidget(self.btn_connect)
        h_btn.addWidget(self.btn_disconnect)
        
        l_conn.addWidget(conn_group)
        l_conn.addWidget(self.status_label)
        l_conn.addWidget(btn_group)
        l_conn.addStretch(1)

        # --- Pulse Window tab (Amplitude + Interval) ---
        tab_amp = QWidget()
        l_amp = QVBoxLayout(tab_amp)
        
        # Max Amplitude Group
        amp_group = QGroupBox("1. Maximum Amplitude Setting")
        h_amp_group = QHBoxLayout(amp_group)
        self.max_amp = QLineEdit(DEFAULT_MAX_AMP); self.max_amp.setValidator(double_validator)
        self.btn_set_amp = QPushButton("Set Max Amp")
        h_amp_group.addWidget(QLabel("Max Amplitude [arb.]"))
        h_amp_group.addWidget(self.max_amp)
        h_amp_group.addWidget(self.btn_set_amp)
        l_amp.addWidget(amp_group)

        # Interval Group
        interval_group = QGroupBox(f"2. Feed-Forward Pulse Window [µs] (Max {MAX_PULSE_TIME_US} µs)")
        l_int_group = QVBoxLayout(interval_group)
        
        h_offset = QHBoxLayout()
        self.offset = QLineEdit("0"); self.offset.setValidator(double_validator); self.offset.setFixedWidth(100)
        h_offset.addWidget(QLabel("Offset (Start Time)"))
        h_offset.addWidget(self.offset)
        h_offset.addStretch(1)
        
        h_duration = QHBoxLayout()
        self.duration = QLineEdit("5"); self.duration.setValidator(double_validator); self.duration.setFixedWidth(100)
        h_duration.addWidget(QLabel("Duration"))
        h_duration.addWidget(self.duration)
        h_duration.addStretch(1)
        
        self.btn_set_interval = QPushButton("Apply Offset & Duration")
        
        l_int_group.addLayout(h_offset)
        l_int_group.addLayout(h_duration)
        l_int_group.addWidget(self.btn_set_interval)
        l_amp.addWidget(interval_group)
        
        # Phase Group
        #phase_group = QGroupBox("3. Constant Phase Setting [deg]")
        #h_phase_group = QHBoxLayout(phase_group)
        #self.phase = QLineEdit("0"); self.phase.setValidator(double_validator)
        #self.btn_set_phase = QPushButton("Set Constant Phase")
        #h_phase_group.addWidget(QLabel("Phase Value [deg]"))
        #h_phase_group.addWidget(self.phase)
        #h_phase_group.addWidget(self.btn_set_phase)
       # l_amp.addWidget(phase_group)

        l_amp.addStretch(1)
        
        # --- Amplitude Waveform tab ---
        tab_ampWave = QWidget()
        l_ampW = QVBoxLayout(tab_ampWave)
        
        self.btn_load_wave = QPushButton("1. Load Waveform (*.npy, *.txt)")
        self.btn_send_wave = QPushButton("2. Send to LLRF")
        self.btn_force_update_amp = QPushButton("3. Refresh Preview")
        
        # Control Bar (Load, Send, Update)
        wave_control_group = QGroupBox("Waveform Control & Shift (Amplitude)")
        h_wave_control = QHBoxLayout(wave_control_group)
        
        # *** CORREZIONE LAYOUT: Pulsanti Waveform Amplitude ***
        # Uso del fattore di stretch per garantire la visibilità
        h_wave_control.addWidget(self.btn_load_wave, 1)
        h_wave_control.addWidget(self.btn_send_wave, 1)
        h_wave_control.addWidget(self.btn_force_update_amp, 1)
        # *******************************************************
        
        l_ampW.addWidget(wave_control_group)

        # Plot Amplitude
        l_ampW.addWidget(QLabel("Live Preview - Amplitude [arb.] (Yellow line)"))
        self.wave_preview = pg.PlotWidget()
        self.wave_preview.setLabel('left', 'Amplitude', units='[arb.]')
        self.wave_preview.setLabel('bottom', 'Time', units='µs')
        self.wave_preview.setYRange(0, 1)
        self.wave_preview.setXRange(0, MAX_PULSE_TIME_US)
        
        # Slider
        slider_group = QGroupBox("Time Shift Preview [µs]")
        h_slider = QVBoxLayout(slider_group)
        self.wave_value_label = QLabel("Shift Amp = 0 µs", alignment=Qt.AlignCenter)
        self.wave_slider = QSlider(Qt.Horizontal)
        self.wave_slider.setMinimum(int(-MAX_PULSE_TIME_US))
        self.wave_slider.setMaximum(int(MAX_PULSE_TIME_US))
        self.wave_slider.setValue(0)
        self.wave_slider.setTickInterval(5)
        self.wave_slider.setTickPosition(QSlider.TicksBelow)
        
        h_slider.addWidget(self.wave_value_label)
        h_slider.addWidget(self.wave_slider)
        
        l_ampW.addWidget(self.wave_preview)
        l_ampW.addWidget(slider_group)
        l_ampW.addStretch(1)

        # --- Phase Waveform tab ---
        tab_phase = QWidget()
        l_phase = QVBoxLayout(tab_phase)
        
        self.btn_load_wavephase = QPushButton("1. Load Waveform (*.npy, *.txt)")
        self.btn_send_wavephase = QPushButton("2. Send to LLRF")
        self.btn_force_update_phase = QPushButton("3. Refresh Preview")
        
        # Control Bar (Load, Send, Update)
        phase_wave_control_group = QGroupBox("Waveform Control & Shift (Phase)")
        h_phase_wave_control = QHBoxLayout(phase_wave_control_group)
        
        # *** CORREZIONE LAYOUT: Pulsanti Waveform Phase ***
        # Uso del fattore di stretch per garantire la visibilità
        h_phase_wave_control.addWidget(self.btn_load_wavephase, 1)
        h_phase_wave_control.addWidget(self.btn_send_wavephase, 1)
        h_phase_wave_control.addWidget(self.btn_force_update_phase, 1)
        # *******************************************************
        
        l_phase.addWidget(phase_wave_control_group)

        # Plot Phase
        l_phase.addWidget(QLabel("Live Preview - Phase [deg.] (Yellow line)"))
        self.wave_preview_phase = pg.PlotWidget()
        self.wave_preview_phase.setLabel('left', 'Phase', units='[deg]')
        self.wave_preview_phase.setLabel('bottom', 'Time', units='µs')
        self.wave_preview_phase.setYRange(-180, 180)
        self.wave_preview_phase.setXRange(0, MAX_PULSE_TIME_US)
        
        # Slider Phase
        slider_group_phase = QGroupBox("Time Shift Preview [µs]")
        h_slider_phase = QVBoxLayout(slider_group_phase)
        self.wave_value_label_phase = QLabel("Shift Phase = 0 µs", alignment=Qt.AlignCenter)
        self.wave_slider_phase = QSlider(Qt.Horizontal)
        self.wave_slider_phase.setMinimum(int(-MAX_PULSE_TIME_US))
        self.wave_slider_phase.setMaximum(int(MAX_PULSE_TIME_US))
        self.wave_slider_phase.setValue(0)
        self.wave_slider_phase.setTickInterval(5)
        self.wave_slider_phase.setTickPosition(QSlider.TicksBelow)
        
        h_slider_phase.addWidget(self.wave_value_label_phase)
        h_slider_phase.addWidget(self.wave_slider_phase)
        
        l_phase.addWidget(self.wave_preview_phase)
        l_phase.addWidget(slider_group_phase)
        l_phase.addStretch(1)


        # --- Restore tab ---
        tab_reset = QWidget()
        l_reset = QVBoxLayout(tab_reset)
        reset_group = QGroupBox("System Reset & Diagnostics")
        l_reset_group = QVBoxLayout(reset_group)
        
        self.btn_restore = QPushButton("RESTORE FACTORY DEFAULTS")
        self.btn_restore.setStyleSheet("background-color: orange; color: black; font-weight: bold;")
        
        l_reset_group.addWidget(self.btn_restore)
        l_reset_group.addWidget(QLabel(" **ATTENZIONE:** Questo comando resetterà tutti i parametri del dispositivo ai valori predefiniti."))
        
        l_reset.addWidget(reset_group)
        l_reset.addStretch(1)

        # Tabs
        self.tabs = QTabWidget()
        for name, tab in [
            ("1. Connection", tab_conn),
            ("2. Pulse Parameters", tab_amp),
            ("3. Amplitude Waveform", tab_ampWave),
            ("4. Phase Waveform" , tab_phase),
            ("5. Diagnostics / Reset", tab_reset)
        ]:
            self.tabs.addTab(tab, name)

        # Main layout
        main = QVBoxLayout(self)
        main.addWidget(self.tabs)
        main.addWidget(QLabel("### System Log:"))
        main.addWidget(self.log_display, 2)
        self.tabs.setMinimumHeight(400)

    def _connect_signals(self):
        # Buttons
        self.btn_connect.clicked.connect(self.on_connect_clicked)
        self.btn_disconnect.clicked.connect(self.on_disconnect_clicked)
        self.btn_set_amp.clicked.connect(self.on_set_amp_clicked)
        self.btn_set_interval.clicked.connect(self.on_set_interval_clicked)
        self.btn_restore.clicked.connect(self.on_restore_clicked)
        #self.btn_set_phase.clicked.connect(self.on_set_phase_clicked)
        
        # Waveform Load/Send
        self.btn_load_wave.clicked.connect(self.on_load_wave_clicked)
        self.btn_load_wavephase.clicked.connect(self.on_load_wave_phase_clicked)
        self.btn_send_wave.clicked.connect(self.on_send_wave_clicked)
        self.btn_send_wavephase.clicked.connect(self.on_send_wavephase_clicked)
        
        # Forced Manual Update
        self.btn_force_update_amp.clicked.connect(lambda: self.update_wave_preview(self.wave_slider.value()))
        self.btn_force_update_phase.clicked.connect(lambda: self.update_wave_preview_phase(self.wave_slider_phase.value()))
        
        # Sliders (Automatic Update)
        self.wave_slider.valueChanged.connect(self.on_wave_slider_changed)
        self.wave_slider_phase.valueChanged.connect(self.on_wave_slider_changed_phase)

        # Logging
        self.log_signal.connect(self._append_log)

    # ====================================================================
    # HELPER METHODS (Logging, Workers, Validation)
    # ====================================================================

    def _append_log(self, text: str):
        """Append text to the QPlainTextEdit (main thread)."""
        self.log_display.appendPlainText(text)
        sb = self.log_display.verticalScrollBar()
        sb.setValue(sb.maximum())

    def log(self, text: str):
        """Thread-safe call to append log."""
        self.log_signal.emit(text)

    def _run_worker(self, func, *args, on_finished=None, on_error=None):
        worker = LLRFWorker(func, *args)
        worker.log.connect(self.log)
        
        # Funzione per pulire e aggiornare lo stato UI
        def _cleanup(_):
            try:
                self._active_workers.remove(worker)
            except ValueError:
                pass
            self._update_global_state() # Aggiorna lo stato UI

        # Connessione ai callback originali e al cleanup
        if on_finished:
            worker.finished.connect(on_finished)
        worker.finished.connect(_cleanup)
        
        if on_error:
            worker.error.connect(on_error)
        worker.error.connect(_cleanup)

        self._active_workers.append(worker)
        self._update_global_state() # Aggiorna lo stato UI prima di iniziare (disabilita)
        worker.start()
        return worker
    
    def _validate_float_input(self, line_edit, error_msg):
        """Tenta di convertire il testo in float e gestisce l'errore."""
        try:
            return float(line_edit.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid input", error_msg)
            return None

    # ====================================================================
    # ACTION METHODS (LLRF Interaction)
    # ====================================================================

    def on_connect_clicked(self):
        def connect_task():
            conn = LLRFConnection(self.ip.text(), self.user.text(), self.pwd.text())
            conn.connect()
            return conn

        def on_connected(conn):
            self.conn = conn
            self.online = True
            self.log(f"Connected to {self.ip.text()} as {self.user.text()}")

        def on_connect_error(e):
            self.online = False
            QMessageBox.warning(self, "Connection error", f"Could not connect:\n{e}")

        self._run_worker(connect_task, on_finished=on_connected, on_error=on_connect_error)

    def on_disconnect_clicked(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception as e:
                self.log(f"Disconnect error: {e}")
        self.conn = None
        self.online = False
        self.log("Disconnected")
        self._update_global_state() # CHIAMATA DIRETTA, NON C'È THREAD

    def update_timing_fields(self, new_offset, new_duration):
        self.offset.setText(str(new_offset))
        self.duration.setText(str(new_duration))
        self.log_signal.emit(f"Aggiornati campi: Offset={new_offset}, Duration={new_duration}")

    def on_set_amp_clicked(self):
        max_amp = self._validate_float_input(self.max_amp, "Max amplitude must be a number.")
        if max_amp is None or not self.conn:
            return

        self._run_worker(lambda: self.conn.FF_Change_MaxAmp(max_amp),
                             on_finished=lambda _: self.log("Max Amp set"),
                             on_error=lambda e: self.log(f"Error setting max amp: {e}"))

    def on_set_interval_clicked(self):
        offset = self._validate_float_input(self.offset, "Offset must be a number.")
        duration = self._validate_float_input(self.duration, "Duration must be a number.")
        
        wave = self.loaded_wave
        phase = self.loaded_wave_phase
        
        # Logica di correzione del tempo per 2D waveforms (Eseguita nel Main Thread)
        if wave is not None:
            dim_amp = wave.ndim
            if dim_amp == 2:
                # Modifica la wave in place (OK perché nel main thread prima del worker)
                diff = wave[0,1] - offset
                wave[:,1] -= diff
                self.loaded_wave[:,1] = wave[:,1]

        if phase is not None:
            dim_phase = phase.ndim
            if dim_phase == 2:
                # Modifica la wave in place (OK perché nel main thread prima del worker)
                diff_p = phase[0,1] - offset
                phase[:,1] += diff_p

        def update_ui_after_interval_set(_):
            self.log("FF Interval set")
            # Queste chiamate devono essere nel main thread!
            self.update_wave_preview(self.wave_slider.value())
            self.update_wave_preview_phase(self.wave_slider_phase.value())
            self.log("Waveform previews updated")


        if offset is None or duration is None or not self.conn:
            return
        
        self._run_worker(lambda: self.conn.FF_Change_Interval(offset, duration),
                        on_finished=update_ui_after_interval_set,
                        on_error=lambda e: self.log(f"Error setting interval: {e}"))

  #  def on_set_phase_clicked(self):
  #      phase = self._validate_float_input(self.phase, "Phase must be a number.")
  #      if phase is None or not self.conn:
  #          return

  #      self._run_worker(lambda: self.conn.FF_Change_Phase(phase, True),
  #                           on_finished=lambda _: self.log("Constant Phase set"),
  #                           on_error=lambda e: self.log(f"Error setting phase: {e}"))

    def on_restore_clicked(self):
        if not self.conn:
            QMessageBox.warning(self, "Not connected", "Please connect first.")
            return
        self._run_worker(lambda: self.conn.Restore(),
                             on_finished=lambda _: self.log("Defaults restored"),
                             on_error=lambda e: self.log(f"Error restoring defaults: {e}"))

    # ====================================================================
    # WAVEFORM LOGIC
    # ====================================================================

    def _load_waveform_data(self, fname):
        """Helper per caricare i dati e gestire 1D/2D, aggiornando la UI se 2D."""
        try:
            wave = np.load(fname) if fname.endswith(".npy") else np.loadtxt(fname)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not load file:\n{e}")
            self.log(f"ERROR loading waveform: {e}")
            return None
        
        wave = np.asarray(wave)
        if wave.ndim not in (1, 2):
            QMessageBox.critical(self, "Error", f"Unsupported waveform ndim: {wave.ndim}")
            return None
        
        # Aggiorna UI se è un file 2D (Valore, Tempo)
        if wave.ndim == 2:
            time_us = wave[:, 1]
            t_start = time_us[0]
            t_end = time_us[-1]
            pulse_duration = t_end - t_start
            
            self.update_timing_fields(t_start,pulse_duration) # CHIAMATA AL MAIN THREAD
        
        return wave

    def on_load_wave_clicked(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Load waveform", "", "Waveforms (*.npy *.txt)")
        if not fname:
            return

        wave = self._load_waveform_data(fname)
        if wave is None:
            return

        ndim = wave.ndim
        if ndim == 1:
            self.original_wave = wave.copy()/np.max(wave.copy())
            self.loaded_wave = wave.copy()/np.max(wave.copy())
        if ndim == 2:
            self.original_wave = wave.copy()
            self.loaded_wave = wave.copy()
            self.original_wave[:,0]/=np.max(self.original_wave[:,0])
            
        self.log(f"Loaded waveform Amplitude ({wave.ndim}D): {os.path.basename(fname)}")
        self.wave_slider.setValue(0)
        self.update_wave_preview(shift_us=0.0)

    def on_load_wave_phase_clicked(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Load waveform", "", "Waveforms (*.npy *.txt)")
        if not fname:
            return

        wave = self._load_waveform_data(fname)
        if wave is None:
            return

        self.original_wave_phase = wave.copy()
        self.loaded_wave_phase = wave.copy()
        
        self.log(f"Loaded waveform Phase ({wave.ndim}D): {os.path.basename(fname)}")
        self.wave_slider_phase.setValue(0)
        self.update_wave_preview_phase(shift_us_phase=0.0)

    def on_wave_slider_changed(self, value: int):
        if self._slider_active == "phase":
            return
        self._slider_active = "amp"
        try:
            self.wave_value_label.setText(f"Shift Amp = {value} µs")
            self.update_wave_preview(shift_us=float(value))
        finally:
            self._slider_active = None

    def on_wave_slider_changed_phase(self, value: int):
        if self._slider_active == "amp":
            return
        self._slider_active = "phase"
        try:
            self.wave_value_label_phase.setText(f"Shift Phase = {value} µs")
            self.update_wave_preview_phase(shift_us_phase=float(value))
        finally:
            self._slider_active = None

    def _get_waveform_params(self, original_wave):
        """Estrae i parametri per il calcolo e il plot, gestendo 1D e 2D."""
        N = original_wave.shape[0]
        dimension = original_wave.ndim
        signal = original_wave[:, 0].copy() if dimension == 2 else original_wave.copy()

        try:
            init_offset = float(self.offset.text())
            pulse_duration = float(self.duration.text())
        except ValueError:
            init_offset = 0.0
            pulse_duration = MAX_PULSE_TIME_US
            
        if dimension == 2:
            Time_us_orig = original_wave[:, 1]
            pulse_length_for_roll = Time_us_orig[-1] - Time_us_orig[0]
        else:
            Time_us_orig = np.linspace(0, MAX_PULSE_TIME_US, N)
            pulse_length_for_roll = MAX_PULSE_TIME_US

        # Calcola l'indice di cut-off basato sulla durata UI
        index_null = int(N * ( pulse_duration) / MAX_PULSE_TIME_US)
        
        return N, dimension, signal, Time_us_orig, pulse_length_for_roll, index_null

    def update_wave_preview(self, shift_us: float = 0.0):
        if self.original_wave is None: return

        self.setUpdatesEnabled(False)
        try:
            N, dimension, signal, Time_us_orig, pulse_length_for_roll, index_null = \
                self._get_waveform_params(self.original_wave)

            rolled_ind = int(shift_us * N / pulse_length_for_roll)
            active = np.roll(signal, rolled_ind)

            # Riempimento dei vuoti (Amplitude -> Riempie con 1)
            if rolled_ind > 0:
                active[:rolled_ind] = 1
            elif rolled_ind < 0:
                active[rolled_ind:] = 1
            
            signal_to_plot = active.copy()
            if (index_null < N) and (dimension == 1):
                signal_to_plot[index_null:] = 0
            
            # Aggiornamento dello stato per l'invio
            if dimension == 2:
                # Copia il tempo attuale dal loaded_wave (potrebbe essere stato shiftato dall'UI)
                Time_us_current = self.loaded_wave[:,1].copy()
                self.loaded_wave = np.transpose(np.array([signal_to_plot, Time_us_current]))
            else:
                self.loaded_wave = signal_to_plot
            
            # Aggiornamento del Plot
            plot_item = self.wave_preview.getPlotItem()
            plot_item.clearPlots()
            
            current_offset = float(self.offset.text())
            
            if dimension == 1:
                plot_item.plot(Time_us_orig + current_offset, signal_to_plot, pen='y')
            elif dimension == 2:
                # Usa il tempo da loaded_wave che è quello attuale
                plot_item.plot(self.loaded_wave[:,1], signal_to_plot, pen='y')

            self.wave_preview.repaint()
            self.wave_preview.setYRange(0, 1)
            self.wave_preview.setXRange(0, MAX_PULSE_TIME_US)

        finally:
            self.setUpdatesEnabled(True)

    def update_wave_preview_phase(self, shift_us_phase: float = 0.0):
        if self.original_wave_phase is None: return

        self.setUpdatesEnabled(False)
        try:
            N, dimension, signal, Time_us_orig, pulse_length_for_roll, index_null = \
                self._get_waveform_params(self.original_wave_phase)
            
            rolled_ind = int(shift_us_phase * N / pulse_length_for_roll)
            active = np.roll(signal, rolled_ind)

            # Riempimento dei vuoti (Phase -> Riempie con 0)
            if rolled_ind > 0:
                active[:rolled_ind] = 0
            elif rolled_ind < 0:
                active[rolled_ind:] = 0
                
            signal_to_plot = active.copy()
            if (index_null < N) and (dimension == 1):
                signal_to_plot[index_null:] = 0
            
            # Aggiornamento dello stato per l'invio
            if dimension == 2:
                Time_us_current = self.loaded_wave_phase[:,1].copy()
                self.loaded_wave_phase = np.transpose(np.array([signal_to_plot, Time_us_current]))
            else:
                self.loaded_wave_phase = signal_to_plot
            
            # Aggiornamento del Plot
            plot_item = self.wave_preview_phase.getPlotItem()
            plot_item.clearPlots()
            
            current_offset = float(self.offset.text())
            
            if dimension == 1:
                plot_item.plot(Time_us_orig + current_offset, signal_to_plot, pen='y')
            elif dimension == 2:
                plot_item.plot(self.loaded_wave_phase[:,1], signal_to_plot, pen='y')

            self.wave_preview_phase.repaint()
            self.wave_preview_phase.setYRange(-180, 180)
            self.wave_preview_phase.setXRange(0, MAX_PULSE_TIME_US)

        finally:
            self.setUpdatesEnabled(True)
            
    # --- Sending waveform methods ---

    def on_send_wave_clicked(self):
        if self.loaded_wave is None:
            QMessageBox.warning(self, "Error", "No amplitude waveform loaded!")
            return
        if not self.conn:
            QMessageBox.warning(self, "Not connected", "Please connect first.")
            return

        self._run_worker(self.send_wave_task,
                             on_finished=lambda r: self.log(str(r)),
                             on_error=lambda e: self.log(f"Error uploading amplitude waveform: {e}"))

    def on_send_wavephase_clicked(self):
        if self.loaded_wave_phase is None:
            QMessageBox.warning(self, "Error", "No phase waveform loaded!")
            return
        if not self.conn:
            QMessageBox.warning(self, "Not connected", "Please connect first.")
            return

        self._run_worker(self.send_wave_phase_task,
                             on_finished=lambda r: self.log(str(r)),
                             on_error=lambda e: self.log(f"Error uploading phase waveform: {e}"))


    def send_wave_task(self):
        wave = self.loaded_wave
        ndim = wave.ndim
        max_amp = self._validate_float_input(self.max_amp, "Max amp must be number.") or 1.0
        init_t = self._validate_float_input(self.offset, "Offset must be number.") or 0.0

        if ndim == 1:
            if hasattr(self.conn, "Set_Arbitrary_Shape"):
                self.conn.Set_Arbitrary_Shape(wave.copy(), max_amp, init_t=init_t)
            else:
                raise RuntimeError("LLRFConnection has no Set_Arbitrary_Shape method")
            return "Waveform amplitude uploaded (1D)"
        else:
            amplitude = wave[:, 0].copy()
            time = wave[:, 1].copy()
            t_start = float(time[0])
            t_end = float(time[-1])
            
            if hasattr(self.conn, "Set_Arbitrary_Shape_AndTime"):
                self.conn.Set_Arbitrary_Shape_AndTime(amplitude, max_amp, t_start, t_end)
            else:
                self.conn.Set_Arbitrary_Shape(t_end - t_start, amplitude, max_amp, init_t=t_start)
            return "Waveform amplitude uploaded (2D)"
            
    def send_wave_phase_task(self):
        wave_phase = self.loaded_wave_phase
        ndim_phase = wave_phase.ndim
        cent_phase = self._validate_float_input(self.phase, "Phase must be number.") or 0.0
        init_t = self._validate_float_input(self.offset, "Offset must be number.") or 0.0
        
        if ndim_phase == 1:
            if hasattr(self.conn, "Set_Arbitrary_Phase"):
                self.conn.Set_Arbitrary_Phase(wave_phase.copy(), cent_phase, init_t=init_t)
            else:
                raise RuntimeError("LLRFConnection has no Set_Arbitrary_Phase method")
            return "Waveform phase uploaded (1D)"
        else:
            amplitude = wave_phase[:, 0].copy()
            time = wave_phase[:, 1].copy()
            t_start = float(time[0])
            t_end = float(time[-1])
            
            if hasattr(self.conn, "Set_Arbitrary_Phase_AndTime"):
                self.conn.Set_Arbitrary_Phase_AndTime(amplitude, cent_phase, t_start, t_end)
            else:
                self.conn.Set_Arbitrary_Phase(t_end - t_start, amplitude, cent_phase, init_t=t_start)
            return "Waveform phase uploaded (2D)"

    # --- Utility: secret pixmap ---

    def show_secret_pixmap(self):
        if getattr(sys, 'frozen', False):
            script_dir = os.path.dirname(sys.executable)
        else:
            script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))

        script_dir = 'C:\\Users\\Stefano Farina\\Desktop'
        original = os.path.join(script_dir, "test.png")
        converted = os.path.join(script_dir, "Segreto_temp.png")

        try:
            img = Image.open(original)
            img.save(converted, "PNG")
        except Exception as e:
            QMessageBox.warning(self, "Errore", f"Impossibile aprire/convetire immagine:\n{e}")
            self.log(f"PIL error: {e}")
            return

        pixmap = QPixmap(converted)
        if pixmap.isNull():
            QMessageBox.warning(self, "Errore", f"Qt non riesce a caricare l'immagine convertita")
            self.log("QPixmap NULL")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(" Segreto ")
        lbl = QLabel()
        lbl.setPixmap(pixmap)
        lbl.setScaledContents(True)
        layout = QVBoxLayout()
        layout.addWidget(lbl)
        dlg.setLayout(layout)
        dlg.resize(600, 400)
        dlg.exec_()


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    gui = LLRF_GUI()
    gui.show()
    sys.exit(app.exec_())
