# Copyright (C) 2021-2023 Antmicro
# SPDX-License-Identifier: Apache-2.0
import logging
import os

import click

from .config import config
from .design import build_design_from_yaml
from .interface_grouper import InterfaceGrouper
from .kpm_topwrap_client import kpm_run_client
from .verilog_parser import VerilogModuleGenerator, ipcore_desc_from_verilog_module
from .vhdl_parser import VHDLModule, ipcore_desc_from_vhdl_module

click_dir = click.Path(exists=True, file_okay=False, dir_okay=True, readable=True)
click_file = click.Path(exists=True, file_okay=True, dir_okay=False, readable=True)

main = click.Group(help="FPGA Topwrap")


@main.command("build", help="Generate top module")
@click.option(
    "--sources", "-s", type=click_dir, help="Specify directory to scan for additional sources"
)
@click.option("--design", "-d", type=click_file, required=True, help="Specify top design file")
@click.option("--part", "-p", help="FPGA part name")
@click.option(
    "--iface-compliance/--no-iface-compliance",
    default=False,
    help="Force compliance checks for predefined interfaces",
)
def build_main(sources, design, part, iface_compliance):
    config.force_interface_compliance = iface_compliance

    if part is None:
        logging.warning(
            "You didn't specify part number. 'None' will be used"
            "and thus your implamentation may fail."
        )

    build_design_from_yaml(design, sources, part)


@main.command("parse", help="Parse HDL sources to ip core yamls")
@click.option(
    "--use-yosys",
    default=False,
    is_flag=True,
    help="Use yosys's read_verilog_feature to parse Verilog files",
)
@click.option(
    "--iface-deduce",
    default=False,
    is_flag=True,
    help="Try to group port into interfaces automatically",
)
@click.option(
    "--iface", "-i", multiple=True, help="Interface name, that ports will be grouped into"
)
@click.option(
    "--dest-dir",
    "-d",
    type=click_dir,
    default="./",
    help="Destination directory for generated yamls",
)
@click.argument("files", type=click_file, nargs=-1)
def parse_main(use_yosys, iface_deduce, iface, files, dest_dir):
    logging.basicConfig(level=logging.INFO)
    dest_dir = os.path.dirname(dest_dir)

    for filename in list(filter(lambda name: os.path.splitext(name)[-1] == ".v", files)):  # noqa
        modules = VerilogModuleGenerator().get_modules(filename)
        iface_grouper = InterfaceGrouper(use_yosys, iface_deduce, iface)
        for verilog_mod in modules:
            ipcore_desc = ipcore_desc_from_verilog_module(verilog_mod, iface_grouper)
            yaml_path = os.path.join(dest_dir, f"gen_{ipcore_desc.name}.yaml")
            ipcore_desc.save(yaml_path)
            logging.info(
                f"Verilog module '{verilog_mod.get_module_name()}'" f"saved in file '{yaml_path}'"
            )

    for filename in list(
        filter(lambda name: os.path.splitext(name)[-1] in [".vhd", ".vhdl"], files)
    ):  # noqa
        # TODO - handle case with multiple VHDL modules in one file
        vhdl_mod = VHDLModule(filename)
        iface_grouper = InterfaceGrouper(False, iface_deduce, iface)
        ipcore_desc = ipcore_desc_from_vhdl_module(vhdl_mod, iface_grouper)
        yaml_path = os.path.join(dest_dir, f"gen_{ipcore_desc.name}.yaml")
        ipcore_desc.save(yaml_path)
        logging.info(f"VHDL Module '{vhdl_mod.get_module_name()}'" f"saved in file '{yaml_path}'")


@main.command("kpm_client", help="Run a client app, that connects to" "a running KPM server")
@click.option(
    "--host", "-h", default="127.0.0.1", help='KPM server address - "127.0.0.1" is default'
)
@click.option("--port", "-p", default=9000, help="KPM server listening port - 9000 is default")
@click.argument("yamlfiles", type=click_file, nargs=-1)
def kpm_client_main(host, port, yamlfiles):
    kpm_run_client(host, port, yamlfiles)
