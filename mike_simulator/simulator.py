import sys
import time
from enum import Enum
from typing import Optional

from mike_simulator.task.factory import Task, TaskFactory
from mike_simulator.config import cfg
from mike_simulator.datamodels import ControlResponse, PatientResponse, MotorState, Constants
from mike_simulator.input.factory import InputHandlerFactory
from mike_simulator.input import InputMethod
from mike_simulator.logger import Logger
from mike_simulator.util import PrintUtil
from mike_simulator.util.helpers import clamp


class IllegalStateException(RuntimeError):
    pass


# Simulator states, transitions occur based on control signals
class SimulatorState(Enum):
    WAITING_FOR_PATIENT = 1
    READY = 2
    RUNNING = 3
    FINISHED = 4


class BackendSimulator:
    def __init__(self):
        self.current_patient: PatientResponse = PatientResponse()
        self.current_state = SimulatorState.WAITING_FOR_PATIENT
        self.current_motor_state: Optional[MotorState] = None
        self.current_task: Optional[Task] = None
        self.logger: Optional[Logger] = None

        self.last_update = -1

        try:
            self.input_handler = InputHandlerFactory.create(InputMethod[cfg.Input.method])
        except Exception as e:
            print(f'Error while setting up input method {cfg.Input.method} {e.args}. '
                  f'Falling back to Keyboard Input...')
            self.input_handler = InputHandlerFactory.create(InputMethod.Keyboard)

        self.frontend_started = False

        self.cycle_counter = 0
        self.start_time = time.time_ns()

        self._reset()

    def goto_state(self, new_state: SimulatorState):
        self.current_state = new_state

    def check_in_state(self, *states) -> bool:
        if self.current_state not in states:
            print(f'!!! Illegal state: expected to be in one of {states}, was in {self.current_state.name} !!!')
            # raise IllegalStateException(f'Expected state to be in one of {states}, was {self.current_state.name}')
            return False
        return True

    def update_patient_data(self, data: PatientResponse):
        #self.check_in_state(SimulatorState.WAITING_FOR_PATIENT)
        PrintUtil.print_normally(f'Received {data}')
        self.current_patient = data
        self._reset()
        try:
            self.current_task = TaskFactory.create(data.Task, self.current_motor_state, self.current_patient)
            self.input_handler.begin_task(self.current_task)
            if cfg.Logging.enabled:
                self.logger = Logger(self.current_patient)
            self.goto_state(SimulatorState.READY)
        except ValueError as err:
            print(err.args)

    def update_control_data(self, data: ControlResponse):
        PrintUtil.print_normally(f'Received {data}')
        if data.EmergencyStop:
            self._reset()
            sys.exit(-1)
        elif data.Restart or data.Close:
            self._reset()
            self.goto_state(SimulatorState.WAITING_FOR_PATIENT)
        elif data.Start:
            if self.check_in_state(SimulatorState.READY, SimulatorState.RUNNING):
                self.current_task.on_start(self.current_motor_state, self.input_handler, data.StartingPosition, data.TargetPosition)
                self.last_update = time.time_ns()
                self.goto_state(SimulatorState.RUNNING)
        elif data.FrontendStarted:
            if self.check_in_state(SimulatorState.RUNNING):
                PrintUtil.print_normally('Frontend started')
                self.frontend_started = True

    def handle_skip(self):
        if self.check_in_state(SimulatorState.READY, SimulatorState.RUNNING):
            self.current_task.on_skip(self.current_motor_state)

    def get_motor_state(self) -> MotorState:
        self._update_motor_state()
        #print(f'Sending {self.current_motor_state}')
        return self.current_motor_state

    def _reset(self):
        self.current_motor_state = MotorState.new()
        self.current_task = None
        self.logger = None
        self.input_handler.finish_task()

    def _update_motor_state(self):
        # Compute delta time
        current_time = time.time_ns()
        delta_time = (current_time - self.last_update) / 1_000_000_000
        self.last_update = current_time

        # Update user input state
        self.input_handler.update_input_state(self.current_motor_state, delta_time)

        # Update motor state based on user input
        input_state = self.input_handler.current_input_state
        pos = self.current_motor_state.Position
        self.current_motor_state.Force = input_state.force
        self.current_motor_state.Position = self.clamp_position(pos + input_state.velocity * delta_time)

        # Update task state (if any)
        if self.current_task is not None:
            self.current_task.on_update(self.current_motor_state, self.input_handler)

            # Check if task is finished
            if self.current_task.is_finished():
                if self.check_in_state(SimulatorState.RUNNING):
                    self.input_handler.finish_task()
                    self.current_task = None
                    self.current_motor_state = MotorState.new(Finished=True)
                    self.goto_state(SimulatorState.FINISHED)

        # Update counter
        elapsed_time = (time.time_ns() - self.start_time) / 1_000_000_000
        self.current_motor_state.Counter = self.cycle_counter
        self.current_motor_state.Time = elapsed_time
        self.cycle_counter += 1

        self.frontend_started = self.frontend_started and self.current_motor_state.TargetState

        if self.logger is not None:
            if self.cycle_counter % Constants.LOG_CYCLES == 0:
                self.logger.log(elapsed_time, self.current_motor_state, self.frontend_started, self.input_handler.current_input_state)

        # Wait 1ms to simulate 1kHz update frequency, accuracy of this depends on OS
        time.sleep(Constants.ROBOT_CYCLE_TIME)

    @staticmethod
    def clamp_position(pos: float):
        return clamp(Constants.MIN_POSITION, Constants.MAX_POSITION, pos)
