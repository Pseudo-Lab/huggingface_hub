# coding=utf-8
# Copyright 2024-present, the HuggingFace Inc. team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Contains a tool to generate `src/huggingface_hub/inference/_generated/types`."""

import argparse
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, List, NoReturn

from helpers import check_and_update_file_content
from ruff.__main__ import find_ruff_bin


huggingface_hub_folder_path = Path(__file__).parents[1] / "src" / "huggingface_hub"
INFERENCE_TYPES_FOLDER_PATH = huggingface_hub_folder_path / "inference" / "_generated" / "types"
MAIN_INIT_PY_FILE = huggingface_hub_folder_path / "__init__.py"
REFERENCE_PACKAGE_PATH = (
    Path(__file__).parents[1] / "docs" / "source" / "en" / "package_reference" / "inference_types.md"
)

IGNORE_FILES = [
    "__init__.py",
    "base.py",
]

BASE_DATACLASS_REGEX = re.compile(
    r"""
    ^@dataclass
    \nclass\s(\w+):\n
""",
    re.VERBOSE | re.MULTILINE,
)

INHERITED_DATACLASS_REGEX = re.compile(
    r"""
    ^@dataclass
    \nclass\s(\w+)\(BaseInferenceType\):
""",
    re.VERBOSE | re.MULTILINE,
)

OPTIONAL_FIELD_REGEX = re.compile(r": Optional\[(.+)\]$", re.MULTILINE)


INIT_PY_HEADER = """
# This file is auto-generated by `utils/generate_inference_types.py`.
# Do not modify it manually.
#
# ruff: noqa: F401

from .base import BaseInferenceType
"""

# Regex to add all dataclasses to ./src/huggingface_hub/__init__.py
MAIN_INIT_PY_REGEX = re.compile(
    r"""
\"inference\._generated\.types\":\s*\[ # module name
    (.*?) # all dataclasses listed
\] # closing bracket
""",
    re.MULTILINE | re.VERBOSE | re.DOTALL,
)

# List of classes that are shared across multiple modules
# This is used to fix the naming of the classes (to make them unique by task)
SHARED_CLASSES = [
    "ClassificationOutputTransform",
    "ClassificationOutput",
]

REFERENCE_PACKAGE_CONTENT = """
<!--⚠️ Note that this file is in Markdown but contain specific syntax for our doc-builder (similar to MDX) that may not be
rendered properly in your Markdown viewer.
-->
<!--⚠️ Note that this file is auto-generated by `utils/generate_inference_types.py`. Do not modify it manually.-->


# Inference types

This page lists the types (e.g. dataclasses) available for each task supported on the Hugging Face Hub.
Each task is specified using a JSON schema, and the types are generated from these schemas - with some customization
due to Python requirements.
Visit [@huggingface.js/tasks](https://github.com/huggingface/huggingface.js/tree/main/packages/tasks/src/tasks)
to find the JSON schemas for each task.

This part of the lib is still under development and will be improved in future releases.


{types}
"""


def _inherit_from_base(content: str) -> str:
    content = content.replace(
        "\nfrom dataclasses import", "\nfrom .base import BaseInferenceType\nfrom dataclasses import"
    )
    content = BASE_DATACLASS_REGEX.sub(r"@dataclass\nclass \1(BaseInferenceType):\n", content)
    return content


def _delete_empty_lines(content: str) -> str:
    return "\n".join([line for line in content.split("\n") if line.strip()])


def _fix_naming_for_shared_classes(content: str, module_name: str) -> str:
    for cls in SHARED_CLASSES:
        cls_definition = f"\nclass {cls}"
        if cls_definition in content:
            # Very hacky way to build "AudioClassificationOutputElement" instead of "ClassificationOutput"
            new_cls_definition = "\nclass " + "".join(part.capitalize() for part in module_name.split("_"))
            if "Classification" in new_cls_definition:
                # to avoid "ClassificationClassificationOutput"
                new_cls_definition += cls.removeprefix("Classification")
            else:
                new_cls_definition += cls
            if new_cls_definition.endswith("ClassificationOutput"):
                # to get "AudioClassificationOutputElement"
                new_cls_definition += "Element"
            content = content.replace(cls_definition, new_cls_definition)
    return content


def _make_optional_fields_default_to_none(content: str):
    lines = []
    for line in content.split("\n"):
        if "Optional[" in line and not line.endswith("None"):
            line += " = None"

        lines.append(line)

    return "\n".join(lines)


def _list_dataclasses(content: str) -> List[str]:
    """List all dataclasses defined in the module."""
    return INHERITED_DATACLASS_REGEX.findall(content)


def fix_inference_classes(content: str, module_name: str) -> str:
    content = _inherit_from_base(content)
    content = _delete_empty_lines(content)
    content = _fix_naming_for_shared_classes(content, module_name)
    content = _make_optional_fields_default_to_none(content)
    return content


def create_init_py(dataclasses: Dict[str, List[str]]):
    """Create __init__.py file with all dataclasses."""
    content = INIT_PY_HEADER
    content += "\n"
    content += "\n".join(
        [f"from .{module} import {', '.join(dataclasses_list)}" for module, dataclasses_list in dataclasses.items()]
    )
    return content


def add_dataclasses_to_main_init(content: str, dataclasses: Dict[str, List[str]]):
    dataclasses_list = sorted({cls for classes in dataclasses.values() for cls in classes})
    dataclasses_str = ", ".join(f"'{cls}'" for cls in dataclasses_list)

    return MAIN_INIT_PY_REGEX.sub(f'"inference._generated.types": [{dataclasses_str}]', content)


def format_source_code(code: str) -> str:
    """Apply formatter on the generated source code."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "tmp.py"
        filepath.write_text(code)
        ruff_bin = find_ruff_bin()
        os.spawnv(os.P_WAIT, ruff_bin, ["ruff", str(filepath), "--fix", "--quiet"])
        os.spawnv(os.P_WAIT, ruff_bin, ["ruff", "format", str(filepath), "--quiet"])
        return filepath.read_text()


def generate_reference_package(dataclasses: Dict[str, List[str]]) -> str:
    """Generate the reference package content."""

    per_task_docs = []
    for task in sorted(dataclasses.keys()):
        lines = [f"[[autodoc]] huggingface_hub.{cls}" for cls in sorted(dataclasses[task])]
        lines_str = "\n\n".join(lines)
        per_task_docs.append(f"\n## {task}\n\n{lines_str}\n\n")

    return REFERENCE_PACKAGE_CONTENT.format(types="\n".join(per_task_docs))


def check_inference_types(update: bool) -> NoReturn:
    """Check AsyncInferenceClient is correctly defined and consistent with InferenceClient.

    This script is used in the `make style` and `make quality` checks.
    """
    dataclasses = {}
    for file in INFERENCE_TYPES_FOLDER_PATH.glob("*.py"):
        if file.name in IGNORE_FILES:
            continue

        content = file.read_text()

        fixed_content = fix_inference_classes(content, module_name=file.stem)
        formatted_content = format_source_code(fixed_content)

        dataclasses[file.stem] = _list_dataclasses(formatted_content)

        check_and_update_file_content(file, formatted_content, update)

    init_py_content = create_init_py(dataclasses)
    init_py_content = format_source_code(init_py_content)
    init_py_file = INFERENCE_TYPES_FOLDER_PATH / "__init__.py"
    check_and_update_file_content(init_py_file, init_py_content, update)

    main_init_py_content = MAIN_INIT_PY_FILE.read_text()
    updated_main_init_py_content = add_dataclasses_to_main_init(main_init_py_content, dataclasses)
    updated_main_init_py_content = format_source_code(updated_main_init_py_content)
    check_and_update_file_content(MAIN_INIT_PY_FILE, updated_main_init_py_content, update)

    reference_package_content = generate_reference_package(dataclasses)
    check_and_update_file_content(REFERENCE_PACKAGE_PATH, reference_package_content, update)

    print("✅ All good! (inference types)")
    exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--update",
        action="store_true",
        help=(
            "Whether to re-generate files in `./src/huggingface_hub/inference/_generated/types/` if a change is detected."
        ),
    )
    args = parser.parse_args()

    check_inference_types(update=args.update)
