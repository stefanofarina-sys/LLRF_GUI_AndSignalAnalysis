import paramiko
from getpass import getpass
import time
import re
import ast
import numpy as np
from scipy.interpolate import interp1d

# -*- coding: utf-8 -*-
import time
import paramiko
from typing import Optional

class LLRFConnection:
    def __init__(self,
                 ip_address: str,
                 username: str,
                 password: Optional[str] = None,
                 keyfile: Optional[str] = None,
                 port: Optional[int] = None):
        self.ip = ip_address
        self.user = username
        self.password = password
        self.keyfile = keyfile
        self.port = port
        self.client: Optional[paramiko.SSHClient] = None
        self.chan = None

    def connect(self, timeout: int = 10, look_for_keys: bool = False, allow_agent: bool = False):
        
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(
            hostname=self.ip,
            #port=self.port,
            username=self.user,
            password=self.password,
            #key_filename=self.keyfile,
            timeout=timeout,
            #look_for_keys=look_for_keys,
            #allow_agent=allow_agent
        )
        # apri una shell interattiva se ti serve un tty
        self.chan = self.client.invoke_shell()
        time.sleep(0.5)
        # svuota il banner iniziale (MOTD)
        while self.chan.recv_ready():
            self.chan.recv(65536)
        command = "libera-ireg access boards.kupvm1.dsp.ff_pulse_shape.mode=Table"
        self.run_command(command)
            
            
    def FF_Change_MaxAmp(self, New_amp, printing = True ):
        cmd_set = f'libera-ireg access boards.kupvm1.dsp.ff_amp.amplitude={New_amp}'
        self.Send(cmd_set, False)

        cmd_check = 'libera-ireg dump boards.kupvm1.dsp.ff_amp.amplitude'
        output = self.Send(cmd_check)
        try:
            value_str = output.split('=')[1].strip().split()[0]
            New_amp_readback = float(value_str)
            if printing == True:
                print("="*40)
                print(f"  NEW USER SET AMPLITUDE: {New_amp_readback}  ")
                print("="*40)            
                return New_amp_readback
        except (IndexError, ValueError) as e:
            print(f"Errore nel leggere il nuovo valore dell'ampiezza: {output}")
            raise e


    def Restore(self):
      
        command_amp = f"libera-ireg access  boards.kupvm1.dsp.ff_pulse_shape.table_amp=1"
        command_phase = f"libera-ireg access  boards.kupvm1.dsp.ff_pulse_shape.table_phase=0"
        self.run_command(command_amp,False)
        self.run_command(command_phase, False)


    def FF_Get_Interval(self):
        cmd_checkoff = 'libera-ireg dump  boards.kupvm1.feed_forward.offset'
        cmd_checkdur = 'libera-ireg dump  boards.kupvm1.feed_forward.duration'
        outputoff = self.Send(cmd_checkoff)
        outputdur = self.Send(cmd_checkdur)
        value_stroff = outputoff.split('=')[1].strip().split()[0]
        readbackoff = float(value_stroff)
        value_strdur = outputdur.split('=')[1].strip().split()[0]
        readbackdur = float(value_strdur)
        return [readbackoff,readbackdur]

    def FF_Get_MaxAmp(self):
        cmd_check = 'libera-ireg dump boards.kupvm1.dsp.ff_amp.amplitude'
        output = self.Send(cmd_check)
        value_str = output.split('=')[1].strip().split()[0]
        New_amp_readback = float(value_str)
        return New_amp_readback


    def FF_Change_Interval(self, Offset, Duration, printing = True):
        if Offset==0 : Offset=0.03
        "   Inserisce la durata dell'impulso e l'offset  unita' di misura micro secondi"
        cmd_set_duration = f'libera-ireg access boards.kupvm1.feed_forward.duration={Duration}'
        cmd_set_Offset = f'libera-ireg access boards.kupvm1.feed_forward.offset={Offset}'
        Out_dur = self.Send(cmd_set_duration)
        Out_off = self.Send(cmd_set_Offset, False)
        try:
            if printing == True:
                value_str = Out_dur.split('=')[1].strip().split()[0]
                New_dur = float(value_str)
                print("="*40)
                print(f"  NEW USER SET Duration: {New_dur}  ")
                value_str = Out_off.split('=')[1].strip().split()[0]
                New_off = float(value_str)
                print(f"  NEW USER SET Offset: {New_off}  ")
                print("="*40) 
                return np.array([New_dur, New_off])

        except (IndexError, ValueError) as e:
             print(f"Error in reading the new interval: {[Offset,Duration]} micros")
             raise 
   
        
   
    
   
    def FF_Change_Phase(self, New_phase, printing):
        cmd_set = f'libera-ireg access boards.kupvm1.dsp.ff_phase.phase={New_phase}'
        if (New_phase < -400 or New_phase>400):
            raise Exception("!!!!!! Errore- The new phase must be between -400 and 400")
        self.Send(cmd_set, False)
        cmd_check = 'libera-ireg dump boards.kupvm1.dsp.ff_phase.phase'
        output = self.Send(cmd_check)
        try:
            value_str = output.split('=')[1].strip().split()[0]
            New_amp_readback = float(value_str)
            if printing == True:
                print("="*40)
                print(f"  NEW USER SET PHASE: {New_amp_readback}  ")
                print("="*40)            
                return New_amp_readback
        except (IndexError, ValueError) as e:
            print(f"Errore nel leggere il nuovo valore dell'ampiezza: {output}")
            raise e

    
    





    def Set_Arbitrary_Shape_AndTime(self,  Arb, Max_amp, init_t, final_t):
             if init_t == 0 : init_t = 0.03
             self.FF_Change_Interval(init_t, final_t - init_t, False)    ##### For stability reason pulse length is foxed to maximum, suppressed where
             if Shape_Duration > 34:
                print("   The arbitary  shape can be fixed only 34 micro seconds after thwe offeset  ")
             offset = init_t
             duration = final_t - init_t
             print("Offset and duration changed")
             if (np.max(Arb) > 1 or np.min(Arb)<0):
                 Max_amp = np.max(Arb)
                 Arb -= np.min(Arb)
                 Arb /= np.max(Arb)
             # zero-out values outside the active pulse region
             initial_index = 0
             self.FF_Change_MaxAmp(Max_amp, False)
             final_index = int(final_t/34*4096)
             length = (final_index - initial_index) + 1
             shape = np.zeros(4096)
             Interpolated_shape =  np.interp(np.linspace(0,1,length), np.linspace(0,1,len(Arb)),Arb) 
             shape[initial_index:final_index +1 ] = Interpolated_shape
             Norm_string = ",".join(f"{x:.6f}" for x in shape )
             commandD = "libera-ireg access boards.kupvm1.dsp.ff_pulse_shape.table_amp=" + Norm_string
             self.run_command(commandD)

             
    def Set_Arbitrary_Shape(self, Arb, Max_amp,init_t):
                    # self.FF_Change_Interval(init_t, 33.99 + init_t)
                     if (np.max(Arb) > 1 or np.min(Arb)<0):
                         Max_amp = np.max(Arb)
                         Arb -= np.min(Arb)
                         Arb /= np.max(Arb)
                         
                     self.FF_Change_MaxAmp(Max_amp, False)
                     Interpolated_shape =  np.interp(np.linspace(0,1,4096), np.linspace(0,1,len(Arb)),Arb)
                     Norm_string = ",".join(f"{x:.6f}" for x in Interpolated_shape )
                     commandD = "libera-ireg access boards.kupvm1.dsp.ff_pulse_shape.table_amp=" + Norm_string
                     self.run_command(commandD)     
             
             
             
             
             
    def Set_Arbitrary_Phase(self, Arb, Cent_phase, init_t ):
                     self.FF_Change_Interval(init_t, 33.99 + init_t)
                     if (np.max(Arb) > 180 or np.min(Arb)<-180):
                         Cent_phase = (np.max(Arb) - np.min(Arb))/2
                         Arb /=np.max(Arb)
                         Arb *=180
                         cent = -((np.max(Arb) - np.min(Arb))/2)
                         Arb += cent
                     self.FF_Change_Phase(Cent_phase, False)
                     # zero-out values outside the active pulse region
                     Interpolated_shape =  np.interp(np.linspace(0,1,4096), np.linspace(0,1,len(Arb)),Arb)
                     Norm_string = ",".join(f"{x:.6f}" for x in Interpolated_shape )
                     commandD = "libera-ireg access boards.kupvm1.dsp.ff_pulse_shape.table_phase=" + Norm_string
                     self.run_command(commandD)

    def Set_Arbitrary_Phase_AndTime(self,  Arb, Cent_phase, init_t, final_t):
             if init_t == 0 : init_t = 0.03
             self.FF_Change_Interval(init_t, final_t - init_t, False)    ##### For stability reason pulse length is foxed to maximum, suppressed where
             if Shape_Duration > 34:
                print("   The arbitary  shape can be fixed only 34 micro seconds after thwe offeset  ")
             offset = init_t
             duration = final_t - init_t
             final_t = offset + duration
             print("Offset and duration changed")
             if (np.max(Arb) > 180 or np.min(Arb)<-180):
                 Cent_phase = (np.max(Arb) - np.min(Arb))/2
                 Arb /=np.max(Arb)
                 Arb *=180
                 Arb -= Cent_phase
             self.FF_Change_Phase(Cent_phase, False)
             initial_index = 0
             final_index = int(final_t/34*4096)
             length = (final_index - initial_index) + 1
             shape = np.zeros(4096)
             Interpolated_shape =  np.interp(np.linspace(0,1,length), np.linspace(0,1,len(Arb)),Arb)
             shape[initial_index:final_index +1 ] = Interpolated_shape
             Norm_string = ",".join(f"{x:.6f}" for x in shape )
             commandD = "libera-ireg access boards.kupvm1.dsp.ff_pulse_shape.table_phase=" + Norm_string
             self.run_command(commandD)
        
        
    def run_command(self, command):
        if not self.client:
            raise Exception("Client not connected. Call connect() first.")
        stdin, stdout, stderr = self.client.exec_command(command)
        out = stdout.read().decode()
        err = stderr.read().decode()
        if err:
            print("STDERR:\n", err)
        return out, err
    
    def Send(self, command, Label=False, timeout=0.5):
        """
        Esegue un comando sul canale interattivo mantenendo la sessione SSH attiva.
        Legge tutto l'output fino a inattività o timeout.
        """
        if not self.chan:
            raise Exception("Channel not open. Call connect() first.")
        
        # Pulisci eventuale output precedente
        while self.chan.recv_ready():
            self.chan.recv(65536)
    
        # Invia il comando
        self.chan.send(command + "\n")
    
        output = ""
        start_time = time.time()
    
        # Leggi fino a che arrivano dati o fino a timeout
        while True:
            if self.chan.recv_ready():
                chunk = self.chan.recv(65536).decode(errors="ignore")
                output += chunk
                start_time = time.time()  # resetta timer ogni volta che arrivano dati
            else:
                time.sleep(0.05)
            
            # Esci se non arriva più niente per un po'
            if time.time() - start_time > timeout:
                break
    
        output = output.strip()
        if Label:
            print(f"\n[Command]: {command}\n[Output]:\n{output}\n")
    
        return output



    def close(self):
        """Chiude client e canale."""
        try:
            if self.chan:
                self.chan.close()
        finally:
            if self.client:
                self.client.close()
            self.chan = None
            self.client = None

    # supporto per "with"
    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        
        self.close()
        return False  # non sopprime eccezioni
  
    def help(self):
        """Print available methods and their purpose."""
        print("="*60)
        print(" LLRFConnection Class - Command Reference Guide")
        print("="*60)
        print("Connection and Control:")
        print("  connect()              → Connect to the LLRF system via SSH.")
        print("  close()                → Close the SSH connection.")
        print("  run_command(cmd)       → Execute a single SSH command.")
        print("  Send(cmd, Label=False) → Send a command through the interactive channel.")
        print()
        print("Feed Forward (FF) Functions:")
        print("  FF_Get_MaxAmp()        → Read the current feed-forward maximum amplitude.")
        print("  FF_Change_MaxAmp(val)  → Set a new maximum amplitude value.")
        print("  FF_Get_Interval()      → Read the feed-forward offset and duration.")
        print("  FF_Change_Interval(off, dur) → Change the FF pulse offset and duration.")
        print()
        print("Ramping Functions:")
        print("  Single_ramp(init_t, final_t, init_amp, final_amp, ...) → Generate and send a single feed-forward ramp.")
        print()
        print("Utility:")
        print("  help()                 → Show this help message.")
        print("="*60)



    def Single_ramp(self, init_t, final_t, init_amp, final_amp, Max_amp , Change_Max_amp = None, change_pulse = False):
        if change_pulse == True:
            self.FF_Change_Interval(init_t, final_t - init_t, False)
            offset = init_t
            duration = final_t - init_t
            print("Offset and duration changed to fit the single ramp")
        else:
            [offset, duration] = self.FF_Get_Interval()
            print(f"Offset and duration kept the same as {[offset, duration]}")
    
        if Change_Max_amp != None:
            self.FF_Change_MaxAmp(Max_amp, False)
        if (final_amp > Max_amp):
            self.FF_Change_MaxAmp(final_amp, False)
            print("Final amplitude bigger than max → Maximum amplitude changed to final one")
        if (init_amp > Max_amp):
            self.FF_Change_MaxAmp(init_amp, False)
            print("Initial amplitude bigger than max → Maximum amplitude changed to initial one")
    
        Max_amp = self.FF_Get_MaxAmp()
        Norm_init_amp = init_amp / Max_amp
        Norm_final_amp = final_amp / Max_amp
    
        Ramp_time = np.linspace(init_t, final_t, 4096)
        Pulse_time = np.linspace(offset, offset + duration, 4096)
        True_time = Ramp_time
        index = (Pulse_time >= init_t) & (Pulse_time <= final_t)

        slope = (Norm_final_amp - Norm_init_amp) / (True_time[-1] - True_time[0])
    
        Normalised_amplitude_vect = slope * (Pulse_time - Pulse_time[0]) + Norm_init_amp
    
        # zero-out values outside the active pulse region
        Normalised_amplitude_vect[np.where(index == False)] = 0
    
        Norm_string = ",".join(f"{x:.6f}" for x in Normalised_amplitude_vect)
        commandD = "libera-ireg access boards.kupvm1.dsp.ff_pulse_shape.table_amp=" + Norm_string
        self.run_command("libera-ireg access boards.kupvm1.dsp.ff_pulse_shape.table_amp=" + Norm_string)
        return Normalised_amplitude_vect




My_first_connection = LLRFConnection('192.168.0.109', 'root', 'Jungle')
