# Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import Any, Dict, List, Optional

from aws_cdk.aws_events import IRuleTarget, RuleTargetInput
from aws_cdk.aws_events_targets import SfnStateMachine
from aws_cdk.aws_iam import Effect, PolicyStatement
from aws_cdk.aws_stepfunctions import CustomState, IntegrationPattern, JsonPath, StateMachineType, TaskInput
from aws_cdk.aws_stepfunctions_tasks import EventBridgePutEventsEntry, GlueStartJobRun
from aws_ddk_core.pipelines import StateMachineStage
from constructs import Construct


class GlueTransformStage(StateMachineStage):
    """
    Class that represents a Glue Transform DDK DataStage.
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        environment_id: str,
        job_name: str,
        crawler_name: str,
        job_args: Optional[Dict[str, Any]] = None,
        state_machine_input: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        DDK Glue Transform stage.

        Stage that contains a step function that runs Glue job, and a Glue crawler afterwards.
        Both the Glue job and the crawler must be pre-created.

        Parameters
        ----------
        scope : Construct
            Scope within which this construct is defined
        id : str
            Identifier of the stage
        environment_id : str
            Identifier of the environment
        job_name : str
            Name of the Glue job to run
        crawler_name : str
            Name of the Glue crawler to run
        job_args : Optional[Dict[str, Any]]
            Glue job arguments
        state_machine_input : Optional[Dict[str, Any]]
            Input of the state machine
        """
        super().__init__(scope, id)

        self._state_machine_input: Optional[Dict[str, Any]] = state_machine_input
        self._event_detail_type: str = f"{id}-event-type"

        # Create GlueStartJobRun step function task
        start_job_run: GlueStartJobRun = GlueStartJobRun(
            self,
            "start-job-run",
            glue_job_name=job_name,
            integration_pattern=IntegrationPattern.RUN_JOB,
            arguments=TaskInput.from_object(
                obj=job_args,
            )
            if job_args
            else None,
            result_path=JsonPath.DISCARD,
        )
        # Create start crawler step function task
        crawl_object = CustomState(
            self,
            "crawl-object",
            state_json={
                "Type": "Task",
                "Resource": "arn:aws:states:::aws-sdk:glue:startCrawler",
                "Parameters": {"Name": crawler_name},
            },
        )
        # Build state machine
        self.create_state_machine(
            f"{id}-state-machine",
            environment_id=environment_id,
            definition=(start_job_run.next(crawl_object)),
            state_machine_type=StateMachineType.STANDARD,
        )
        # Allow state machine to start crawler
        self.state_machine.add_to_role_policy(
            PolicyStatement(
                effect=Effect.ALLOW,
                actions=[
                    "glue:StartCrawler",
                ],
                resources=["*"],
            )
        )

    def get_output_event(self) -> EventBridgePutEventsEntry:
        """
        Get event entry that should be published at the end of the state machine.

        Returns
        -------
        event : EventBridgePutEventsEntry
            Event
        """
        return EventBridgePutEventsEntry(
            detail=TaskInput.from_object(
                obj={"message": f"{self.id} stage has finished."},
            ),
            detail_type=self._event_detail_type,
            source=self.id,
        )

    def get_targets(self) -> Optional[List[IRuleTarget]]:
        """
        Get input targets of the stage.

        Targets are used by Event Rules to describe what should be invoked when a rule matches an event.

        Returns
        -------
        targets : Optional[List[IRuleTarget]]
            List of targets
        """
        return [SfnStateMachine(self._state_machine, input=RuleTargetInput.from_object(self._state_machine_input))]
