import random
from enum import IntEnum
from typing import Optional

from mike_simulator.assessment import Assessment
from mike_simulator.auto_movement.factory import AutoMover, AutoMoverFactory
from mike_simulator.datamodels import MotorState, PatientResponse
from mike_simulator.input import InputHandler
from mike_simulator.util import PrintUtil


class S(IntEnum):
    STANDBY = 0
    MOVING_TO_START = 1
    USER_INPUT = 2

    FINISHED = -1


class PreciseReachAssessment(Assessment):
    def __init__(self, motor_state: MotorState, patient: PatientResponse) -> None:
        super().__init__(S.STANDBY)

        self.direction = 1.0 if patient.LeftHand else -1.0

        # Used for automatic movement to starting position
        self.auto_mover: Optional[AutoMover] = None

        # Compute randomized list of 20 flexion/extension phases (10 each)
        count = patient.PhaseTrialCount
        self.phases = [True]*count + [False]*count
        random.shuffle(self.phases)

        # Initialize trial
        self._prepare_next_trial_or_finish(motor_state)

    def _prepare_next_trial_or_finish(self, motor_state: MotorState):
        if motor_state.TrialNr == len(self.phases):
            self.goto_state(S.FINISHED)
        else:
            # Set start and end position according to random phase
            if self.phases[motor_state.TrialNr]:
                motor_state.StartingPosition = 20.0 * self.direction
                motor_state.TargetPosition = 60.0 * self.direction
            else:
                motor_state.StartingPosition = 60.0 * self.direction
                motor_state.TargetPosition = 20.0 * self.direction

            motor_state.TrialNr += 1
            self.goto_state(S.STANDBY)

    def on_start(self, motor_state: MotorState, input_handler: InputHandler):
        if self.in_state(S.USER_INPUT):
            # Time is up, lock movement and wait for next trial to start (if any)
            motor_state.TargetState = False
            input_handler.lock_movement()
            self._prepare_next_trial_or_finish(motor_state)
        if self.in_state(S.STANDBY):
            # Direct robot to move to starting position within 3 seconds
            self.auto_mover = AutoMoverFactory.make_linear_mover(motor_state.Position, motor_state.StartingPosition, 3.0)
            self.goto_state(S.MOVING_TO_START)

    def on_update(self, motor_state: MotorState, input_handler: InputHandler):
        if self.in_state(S.MOVING_TO_START):
            # Automatic movement towards starting position
            if motor_state.move_using(self.auto_mover).has_finished():
                # Allow user movement until validate is clicked
                motor_state.TargetState = True
                input_handler.unlock_movement()
                self.goto_state(S.USER_INPUT)
        elif self.in_state(S.USER_INPUT):
            # Print current position
            PrintUtil.print_inplace(f'Current pos: {motor_state.Position:.3f}°')