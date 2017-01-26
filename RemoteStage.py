#####################################################################
#                                                                   #
# labscript_devices/RemoteStage.py                                  #
#                                                                   #
# Copyright 2016, Monash University                                 #
#                                                                   #
# This file is part of labscript_devices, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################

if __name__ != "__main__":

    from labscript_devices import labscript_device, BLACS_tab, BLACS_worker
    from labscript import StaticAnalogQuantity, Device, LabscriptError, set_passed_properties
    import numpy as np
    minval=0
    maxval=76346

    @labscript_device
    class RemoteStage(Device):
        allowed_children = [StaticAnalogQuantity]
        generation = 0
        
        @set_passed_properties(property_names = {"connection_table_properties" : [""]})
        def __init__(self, name, server = ""):
            Device.__init__(self, name, None, None)
            self.BLACS_connection = server
            
        def generate_code(self, hdf5_file):
            data_dict = {}
            for stage in self.child_devices:
                # Call these functions to finalise the stage, they are standard functions of all subclasses of Output:
                ignore = stage.get_change_times()
                stage.make_timeseries([])
                stage.expand_timeseries()
                connection = [int(s) for s in stage.connection.split() if s.isdigit()][0]
                value = stage.raw_output[0]
                if not minval <= value <= maxval:
                    # error, out of bounds
                    raise LabscriptError('%s %s has value out of bounds. Set value: %s Allowed range: %s to %s.'%(stage.description,stage.name,str(value),str(minval),str(maxval)))
                data_dict[str(stage.connection)] = value
            dtypes = [(conn, int) for conn in data_dict]
            data_array = np.zeros(1, dtype=dtypes)
            for conn in data_dict:
                data_array[0][conn] = data_dict[conn] 
            grp = hdf5_file.create_group('/devices/'+self.name)
            grp.create_dataset('static_values', data=data_array)

    from blacs.tab_base_classes import Worker, define_state
    from blacs.tab_base_classes import MODE_MANUAL, MODE_TRANSITION_TO_BUFFERED, MODE_TRANSITION_TO_MANUAL, MODE_BUFFERED  

    from blacs.device_base_class import DeviceTab

    @BLACS_tab
    class ZaberstageControllerTab(DeviceTab):
        def initialise_GUI(self):
            # Capabilities
            self.base_units = 'steps'
            self.base_min = 0
            self.base_step = 100
            self.base_decimals = 0
            
            self.device = self.settings['connection_table'].find_by_name(self.device_name)
            self.num_stages = len(self.device.child_list)
            
            # Create the AO output objects
            ao_prop = {}
       
                     
            base_max = 76346
            
            ao_prop["0"] = {'base_unit':self.base_units,
                                   'min':self.base_min,
                                   'max':base_max,
                                   'step':self.base_step,
                                   'decimals':self.base_decimals
                                  }
                                    
            # Create the output objects    
            self.create_analog_outputs(ao_prop)        
            # Create widgets for output objects
            dds_widgets,ao_widgets,do_widgets = self.auto_create_widgets()
            # and auto place the widgets in the UI
            self.auto_place_widgets(("Zaber Stages",ao_widgets))
            
            # Store the Measurement and Automation Explorer (MAX) name
            self.server = str(self.settings['connection_table'].find_by_name(self.device_name).BLACS_connection)
            
            # Set the capabilities of this device
            self.supports_remote_value_check(False)
            self.supports_smart_programming(False) 
        
        def initialise_workers(self):
            # Create and set the primary worker
            self.create_worker("main_worker",ZaberWorker,{'server':self.server})
            self.primary_worker = "main_worker"

    @BLACS_worker    
    class ZaberWorker(Worker):
        def init(self):
            
            global h5py; import labscript_utils.h5_lock, h5py
            global zprocess; import zprocess
            
            self.host, self.port = self.server.split(':')
            
            data = 'initialise'
            response = self.send_data(data)
            if response == 'ok':
                return True
            else:
                raise Exception('invalid response from server: ' + str(response))
        

        def send_data(self, data):
            return zprocess.zmq_get(self.port, self.host, data=data, timeout=10)

        def transition_to_buffered(self,device_name,h5file,initial_values,fresh):
            with h5py.File(h5file) as hdf5_file:
                group = hdf5_file['/devices/'+device_name]
                if 'static_values' in group:
                    focus = group['static_values'][0][0]


            response = self.send_data("%s %s"%("transition_to_buffered", focus))
            
            if response != 'ok':
                raise Exception('Failed to transition to buffered. Message from server was: %s'%response)
              
            return {"0":focus}



        def program_manual(self,values):
            #for now, there is no manual mode
            return values
        
        
        def transition_to_manual(self):
            response = self.send_data("transition_to_manual")
            if response != 'ok':
                raise Exception('Failed to transition to manual.  Message from server was: %s'%response)
                
            return True
            
        def abort(self):
            response = self.send_data("transition_to_manual")
            if response != 'ok':
                raise Exception('Failed to abort.  Message from server was: %s'%response)
                
            return True
            
        def abort_buffered(self):
            return self.abort()
            
        def abort_transition_to_buffered(self):
            return self.abort()
            
        def status(self, region):
            return self.send_data("status %s"%region)


#### Some common stage control functions that the Pi will use on the remote side, but can also be used when importing this file to manually control the stages
import time, struct

def connect():
    import serial
    global ser
    ser = serial.Serial("/dev/ttyUSB0", 9600, 8, 'N', 1, timeout=0.5)
    return ser

def send(device, command, data=0):
    # send a packet using the specified device number, command number, and data
    # The data argument is optional and defaults to zero
    packet = struct.pack('<BBl', device, command, data)
    ser.write(packet)

def receive():
    # return 6 bytes from the receive buffer
    # there must be 6 bytes to receive (no error checking)
    
    r = ser.read(6)
    if r:
        r = struct.unpack('<BBl',r)
    return r

## Give stages sensible names rather than remembering which number they are
mirror_stage = 1
lens_stage = 2

# List of main commands we'll be using (can always use others by their number)
home = 1
move = 20
get_position = 60
get_setting = 53
device_mode = 40

# list of positions
## MOT positions:
mirror_mot_position = 76346
lens_mot_position = 0

# Imaging positions:
mirror_imaging_position = 30000
lens_imaging_position = 76346

def check_stage_position(stage):
    # Checks to see if the stage is in the desired position yet.
    # Make sure that you've told the stage to go there first, otherwise you'll be stuck in this loop forever!
    send(stage,get_position)
    while True:
        value = receive()
        if value[0] == stage and value[1] == get_position:
            actual_position = value[2]
            return actual_position

def wait_until_in_position(stage,desired_position):
    actual_position = -1
    while actual_position != desired_position:
        actual_position = check_stage_position(stage)

def move_to_MOT():
    # Move objective out
    send(lens_stage,move,lens_mot_position)
    #wait about the time it should take
    time.sleep(3.5)
    #check that it's out
    wait_until_in_position(lens_stage,lens_mot_position)

    # Move mirror in
    send(mirror_stage,move,mirror_mot_position)
    #Wait about the time it should take
    time.sleep(1.5)
    #Check where the mirror is until it's where we told it to go
    wait_until_in_position(mirror_stage,mirror_mot_position)


def move_to_imaging(focus = lens_imaging_position):
    focus = int(focus)
    # Move the mirror out first
    send(mirror_stage,move,mirror_imaging_position)
    #Wait about the time it should take
    time.sleep(1.5)
    #Check where the mirror is until it's where we told it to go
    wait_until_in_position(mirror_stage,mirror_imaging_position)

    # Now move lens in
    send(lens_stage,move,focus)
    #wait about the time it should take
    time.sleep(3.5)
    #check that it's out
    wait_until_in_position(lens_stage,focus)

### End of common functions.

### This section to run on the Raspberry Pi to control the stages
if __name__ == "__main__":
    
    from zprocess import zmq_get, ZMQServer
    import threading
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM) 
    GPIO.setup(23, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

    # Set up the process which will run during the experiment
    
    

    class ExperimentServer(ZMQServer):
        def __init__(self, *args, **kwargs):
            ZMQServer.__init__(self, *args, **kwargs)
            self.buffered = False
            self.initialised = False
            self.abort = threading.Event()

        def run_experiment(self,focus):
            
            # Now we're waiting for the triggers and ready to go
            while not GPIO.input(23) and not self.abort.is_set():
                GPIO.wait_for_edge(23, GPIO.RISING, timeout=1000)
            if self.abort.is_set():
                return
            move_to_imaging(focus)
            
            while GPIO.input(23) and not self.abort.is_set():
                GPIO.wait_for_edge(23, GPIO.FALLING, timeout=1000)
            if self.abort.is_set():
                return
            move_to_MOT()

        def initialise(self):
            print "Initialising"
            # connect to stages
            connect()

            # check if the stages have been homed.
            # safest to do lens first, in case it has fallen down and is resting on the mirror.
            send(lens_stage, get_setting, device_mode)
            lens_settings = receive()[2]
            if len(bin(lens_settings)) < 10 or not int(bin(lens_settings)[-8]):
                #lens stage is not homed, let's home it now.
                print "Homing lens stage"
                send(lens_stage,home)
            # and now the mirror
            send(mirror_stage, get_setting, device_mode)
            mirror_settings = receive()[2]
            if len(bin(mirror_settings)) < 10 or not int(bin(mirror_settings)[-8]):
                #mirror stage is not homed, let's home it now.
                print "Homing mirror stage"
                send(mirror_stage,home)
            # Now initialise into the MOT position
            print "Moving to MOT position"
            move_to_MOT()

            self.initialised = True
            return 'ok'

        def handler(self, message):
            print message
            message_parts = message.split(' ')
            cmd = message_parts[0]
            
            if not self.initialised:
                if cmd != 'initialise':
                    return 'Server not yet initialised. Please send the initialise command'
                    
                else:
                    return self.initialise()

            if cmd == 'initialise':
                self.buffered = False
                return self.initialise()
                
            elif cmd == 'transition_to_buffered':
                self.abort.clear()
                focus = message_parts[1]
                # first, check that the stages are in the MOT position.
                lens_position = check_stage_position(lens_stage)
                mirror_position = check_stage_position(mirror_stage)

                if lens_position != lens_mot_position or mirror_position != mirror_mot_position:
                    move_to_MOT()
                # now tell parent that we're ready to go
                ret_message = 'ok'            
                self.experiment = threading.Thread(target = self.run_experiment, args = (focus,))
                self.experiment.daemon = True
                self.experiment.start()
                self.buffered = True

            elif cmd == 'transition_to_manual':
                self.abort.set()
                self.experiment.join()
                lens_position = check_stage_position(lens_stage)
                mirror_position = check_stage_position(mirror_stage)
                if lens_position != lens_mot_position or mirror_position != mirror_mot_position:
                    move_to_MOT()
                self.buffered = False
                ret_message = 'ok'

            else:
                ret_message = 'Unknown command %s'%cmd
                
            return ret_message
    experiment_server = ExperimentServer(42522)
    while True:
        time.sleep(1)
