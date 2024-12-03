# Copyright (c) 2023-2024 Antmicro <www.antmicro.com>
# SPDX-License-Identifier: Apache-2.0

import logging
import os
import threading
from base64 import b64encode
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, TypedDict, Union

import yaml
from pipeline_manager_backend_communication.communication_backend import (
    CommunicationBackend,
)
from pipeline_manager_backend_communication.misc_structures import MessageType
from pipeline_manager_backend_communication.utils import convert_message_to_string
from typing_extensions import NotRequired

from topwrap.util import JsonType

from .design import DesignDescription
from .design_to_kpm_dataflow_parser import kpm_dataflow_from_design_descr
from .kpm_common import RPCparams
from .kpm_dataflow_parser import kpm_dataflow_to_design
from .util import read_json_file, save_file_to_json
from .kpm_dataflow_validator import DataflowValidator
from .yamls_to_kpm_spec_parser import ipcore_yamls_to_kpm_spec


class RPCEndpointReturnType(TypedDict):
    type: int
    content: NotRequired[Union[str, JsonType]]


class RPCExportEndpointReturnType(RPCEndpointReturnType):
    filename: str


class RPCMethods:
    def __init__(self, params: RPCparams, client: Optional[CommunicationBackend] = None):
        self.host = params.host
        self.port = params.port
        self.yamlfiles = params.yamlfiles
        self.build_dir = params.build_dir
        self.design = params.design
        self.client = client
        # Use the $XDG_DATA_HOME as a destination for saving the dataflow, which defaults to ~/.local/share
        xdg_data_home_var = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser()
        self.default_save_file = xdg_data_home_var / "topwrap/dataflow_latest_save.json"
        self.initial_load = True

    def app_capabilities_get(self) -> Dict[Literal["stoppable_methods"], List[str]]:
        return {"stoppable_methods": ["dataflow_run"]}

    def specification_get(self) -> RPCEndpointReturnType:
        logging.info(f"Specification get request from {self.host}:{self.port}")

        specification = ipcore_yamls_to_kpm_spec(self.yamlfiles)
        return {"type": MessageType.OK.value, "content": specification}

    def dataflow_validate(self, dataflow: JsonType) -> RPCEndpointReturnType:
        logging.info(f"Dataflow validation request received from {self.host}:{self.port}")
        messages = DataflowValidator(dataflow).validate_kpm_design()
        if messages["errors"]:
            # note: only the first error is sent to the KPM frontend
            return {"type": MessageType.ERROR.value, "content": messages["errors"][0]}
        elif messages["warnings"]:
            return {
                "type": MessageType.WARNING.value,
                "content": messages["warnings"][0],
            }
        else:
            return {"type": MessageType.OK.value, "content": "Design is valid"}

    def dataflow_run(self, dataflow: JsonType) -> RPCEndpointReturnType:
        logging.info(f"Dataflow run request received from {self.host}:{self.port}")
        errors = _kpm_run_handler(dataflow, self.yamlfiles, self.build_dir)
        if errors:
            # note: only the first error is sent to the KPM frontend
            return {"type": MessageType.ERROR.value, "content": errors[0]}
        else:
            return {"type": MessageType.OK.value, "content": "Build succeeded"}

    def dataflow_stop(self, method: str) -> RPCEndpointReturnType:
        logging.info(f"Dataflow stop request from {self.host}:{self.port}")
        return {"type": MessageType.OK.value}

    def dataflow_export(self, dataflow: JsonType) -> RPCExportEndpointReturnType:
        logging.info(f"Dataflow export request received from {self.host}:{self.port}")
        yaml_str, filename = _kpm_export_handler(dataflow, self.yamlfiles)
        # content sent to KPM frontend needs to be base64 encoded, but
        # b64encode expects a bytes-like object as an argument therefore
        # the string needs to be converted to bytes first and then converted
        # back to string because "content" field is expected to be a string
        yaml_b64encoded = b64encode(yaml_str.encode("utf-8")).decode("utf-8")
        return {"type": MessageType.OK.value, "content": yaml_b64encoded, "filename": filename}

    def dataflow_import(
        self, external_application_dataflow: str, mime: str, base64: bool
    ) -> RPCEndpointReturnType:
        logging.info(f"Dataflow import request received from {self.host}:{self.port}")
        yaml_str = convert_message_to_string(external_application_dataflow, base64, mime)
        dataflow = _kpm_import_handler(yaml_str, self.yamlfiles)
        return {"type": MessageType.OK.value, "content": dataflow}

    async def frontend_on_connect(self):
        """Gets run when frontend connects, loads initial design"""
        logging.debug("frontend on connect")
        if self.client is None:
            logging.debug("The client to send a request to is not defined")
            return
        if self.default_save_file.exists() and not self.initial_load:
            latest_dataflow = read_json_file(self.default_save_file)
            await self.client.request("graph_change", {"dataflow": latest_dataflow})
        elif self.design is not None:
            self.initial_load = False
            with open(self.design) as design_file:
                read_file = design_file.read()
                dataflow = _kpm_import_handler(read_file, self.yamlfiles)
                await self.client.request("graph_change", {"dataflow": dataflow})

    async def nodes_on_change(self, **kwargs: Any):
        await _kpm_handle_graph_change(self)

    async def properties_on_change(self, **kwargs: Any):
        await _kpm_handle_graph_change(self)

    async def connections_on_change(self, **kwargs: Any):
        await _kpm_handle_graph_change(self)

    async def position_on_change(self, **kwargs: Any):
        await _kpm_handle_graph_change(self)


async def _kpm_handle_graph_change(rpc_object: RPCMethods):
    if rpc_object.client is None:
        return
    current_graph = await rpc_object.client.request("graph_get")
    save_file_to_json(
        rpc_object.default_save_file.parent,
        rpc_object.default_save_file.name,
        current_graph["result"]["dataflow"],
    )


def _kpm_import_handler(data: str, yamlfiles: List[Path]) -> JsonType:
    specification = ipcore_yamls_to_kpm_spec(yamlfiles)
    design_descr = DesignDescription.from_dict(yaml.safe_load(data))
    return kpm_dataflow_from_design_descr(design_descr, specification)


def _design_from_kpm_data(data: JsonType, yamlfiles: List[Path]) -> DesignDescription:
    specification = ipcore_yamls_to_kpm_spec(yamlfiles)
    return kpm_dataflow_to_design(data, specification)


def _kpm_run_handler(data: JsonType, yamlfiles: List[Path], build_dir: Path) -> List[str]:
    """Parse information about design from KPM dataflow format into Topwrap's
    internal representation and build the design.
    """
    messages = DataflowValidator(data).validate_kpm_design()
    if not messages["errors"]:
        design = _design_from_kpm_data(data, yamlfiles)
        name = design.design.name or "top"
        ipc = design.to_ip_connect()
        ipc.generate_top(name, build_dir)
        ipc.generate_fuse_core(build_dir=build_dir, top_module_name=name)
    return messages["errors"]


def _generate_design_filename() -> str:
    """Return a design description YAML file name where the design
    description will be written to.
    """
    return datetime.now().strftime("kpm_design_%Y%m%d_%H%M%S.yaml")


def _kpm_export_handler(dataflow: JsonType, yamlfiles: List[Path]) -> Tuple[str, str]:
    """Convert created dataflow into Topwrap's design description YAML.

    :param dataflow: dataflow JSON from KPM
    :param yamlfiles: additional YAML files containing IP core descriptions

    :return: pair: converted YAML string, automatically generated filename
    with current timestamp
    """
    filename = _generate_design_filename()
    design = _design_from_kpm_data(dataflow, yamlfiles)
    return design.to_yaml(), filename


async def kpm_run_client(
    rpc_params: RPCparams, client_ready_event: Optional[threading.Event] = None
):
    client = CommunicationBackend(rpc_params.host, rpc_params.port)
    logging.debug("Initializing RPC client")
    await client.initialize_client(RPCMethods(rpc_params, client))
    if client_ready_event is not None:
        client_ready_event.set()
    logging.debug("starting json rpc client")
    await client.start_json_rpc_client()
