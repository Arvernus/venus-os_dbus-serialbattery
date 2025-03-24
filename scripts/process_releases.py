import requests
import json
import zipfile
import io
import logging
import yaml
import importlib.util
import sys
import subprocess
import re
from typing import List, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def install_package(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

def fetch_releases():
    url = "https://api.github.com/repos/Arvernus/iRock-Modbus/releases"
    logger.info(f"Fetching releases from {url}")
    response = requests.get(url)
    response.raise_for_status()
    return response.json()

def fetch_validate_yaml():
    url = "https://raw.githubusercontent.com/Arvernus/iRock-Modbus/main/validate_yaml.py"
    logger.info(f"Fetching validate_yaml.py from {url}")
    response = requests.get(url)
    response.raise_for_status()
    return response.content

def load_validate_yaml_module(data):
    spec = importlib.util.spec_from_loader("validate_yaml", loader=None)
    validate_yaml = importlib.util.module_from_spec(spec)
    exec(data, validate_yaml.__dict__)
    sys.modules["validate_yaml"] = validate_yaml
    return validate_yaml

def extract_file_from_zip(data, filename):
    logger.info(f"Extracting {filename} from ZIP")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            logger.info("ZIP file opened successfully")
            for file_name in z.namelist():
                if file_name.endswith(filename):
                    with z.open(file_name) as f:
                        logger.info(f"{filename} found in ZIP file")
                        return f.read()
            logger.error(f"{filename} not found in the ZIP file")
    except zipfile.BadZipFile:
        logger.error("Failed to open ZIP file")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
    return None

def process_release_data(release, validate_yaml) -> Tuple[dict, dict]:
    logger.info(f"Processing release: {release['tag_name']}")
    data_url = release['zipball_url']
    logger.info(f"Downloading data from {data_url}")
    data_response = requests.get(data_url)
    data_response.raise_for_status()
    data = data_response.content

    data_yaml = extract_file_from_zip(data, 'data.yaml')
    if data_yaml:
        data_yaml = yaml.safe_load(data_yaml)
        registers = validate_yaml.generate_registers(data_yaml)
        registers_dict = registers.register_to_dict()
        cell_registers_dict = registers.cell_register_to_dict()
        logger.info(f"Generated registers: {registers_dict}")
        logger.info(f"Generated cell registers: {cell_registers_dict}")
        return registers_dict, cell_registers_dict
    else:
        logger.error(f"Failed to process data.yaml from release {release['tag_name']}")

def replace_constant(content: str, constant_name: str, new_data: List[dict]) -> str:
    pattern = re.compile(rf"{constant_name} = \[.*?\]", re.DOTALL)
    replacement = f"{constant_name} = [\n"
    for item in new_data:
        replacement += f"    {repr(item)},\n"
    replacement += "]"
    return pattern.sub(replacement, content)

def main():
    logger.info("Starting process to fetch and process releases")
    try:
        import jsonschema
    except ImportError:
        logger.info("jsonschema not found, installing...")
        install_package("jsonschema")
    
    validate_yaml_data = fetch_validate_yaml()
    validate_yaml = load_validate_yaml_module(validate_yaml_data)
    
    releases = fetch_releases()
    data: List[dict] = []
    cell_data: List[dict] = []
    for release in releases:
        registers_dict, cell_registers_dict = process_release_data(release, validate_yaml)
        data.append(registers_dict)
        cell_data.append(cell_registers_dict)
    
    with open("./dbus-serialbattery/bms/irock.py", 'r') as file:
        content = file.read()
    
    content = replace_constant(content, "IROCK_MODBUS_REGISTERS", data)
    content = replace_constant(content, "IROCK_MODBUS_CELL_REGISTERS", cell_data)
    
    with open("./dbus-serialbattery/bms/irock.py", 'w') as file:
        file.write(content)
    
    logger.info("Finished processing all releases")
    
if __name__ == "__main__":
    main()
