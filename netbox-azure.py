import time
import requests
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient

# Azure credentials and subscription details
subscription_id = ''  # Replace with your actual subscription ID
resource_group_name = ''  # Replace with your resource group
location = ''

# NetBox API details
netbox_url = 'https://netbox/api'
netbox_token = ''



headers = {
    'Authorization': f'Token {netbox_token}',
    'Content-Type': 'application/json',
    'Accept': 'application/json',
}

# Authenticate with Azure
credential = DefaultAzureCredential()
compute_client = ComputeManagementClient(credential, subscription_id)
network_client = NetworkManagementClient(credential, subscription_id)

# Function to get VM information from Azure
def get_azure_vms():
    """Fetch all virtual machines from Azure."""
    vms = compute_client.virtual_machines.list(resource_group_name)
    vm_info_list = []

    for vm in vms:
        vm_size = vm.hardware_profile.vm_size
        vm_size_info = compute_client.virtual_machine_sizes.list(location)
        vm_size_details = next((size for size in vm_size_info if size.name == vm_size), None)

        if vm_size_details:
            vcpus = vm_size_details.number_of_cores
            memory = vm_size_details.memory_in_mb
        else:
            vcpus = 0
            memory = 0

        # Get OS disk size
        os_disk_size_gb = 0
        if vm.storage_profile.os_disk.disk_size_gb:
            os_disk_size_gb = vm.storage_profile.os_disk.disk_size_gb  # Disk size is already in GB
            os_disk_size_mb = os_disk_size_gb * 1024  # Convert disk size to MB
            print(f"OS Disk Size for VM {vm.name}: {os_disk_size_gb} GB ({os_disk_size_mb} MB)")
        else:
            print(f"No OS Disk Size found for VM {vm.name}")
            os_disk_size_mb = 0

        vm_info = {
            'name': vm.name,
            'location': vm.location,
            'vm_id': vm.id,
            'type': vm.type,
            'vcpus': vcpus,
            'memory': memory,  # Memory size in MB
            'disk': os_disk_size_mb,  # Disk size in MB
            'network_interfaces': []
        }

        # Get network interfaces for the VM
        nic_refs = vm.network_profile.network_interfaces if vm.network_profile else []
        vm_info['network_interfaces'] = [nic.id for nic in nic_refs]

        vm_info_list.append(vm_info)

    return vm_info_list

# Function to get network details
def get_network_info(network_interface_id):
    """Fetch private and public IP details for a network interface."""
    network_interface_name = network_interface_id.split('/')[-1]
    print(f"Fetching network details for: {network_interface_name}")

    network_interface = network_client.network_interfaces.get(resource_group_name, network_interface_name)
    ip_configurations = network_interface.ip_configurations
    network_info = []

    for ip_config in ip_configurations:
        private_ip = ip_config.private_ip_address
        public_ip = None

        if ip_config.public_ip_address:
            public_ip_id = ip_config.public_ip_address.id
            public_ip_name = public_ip_id.split('/')[-1]
            public_ip_obj = network_client.public_ip_addresses.get(resource_group_name, public_ip_name)
            public_ip = public_ip_obj.ip_address

        network_info.append({
            'interface_name': network_interface_name,
            'private_ip': private_ip,
            'public_ip': public_ip,
        })

    return network_info

# Function to get the NetBox VM ID by name
def get_netbox_vm_id_by_name(vm_name):
    """Search for the VM by its name and return its ID."""
    url = f"{netbox_url}/virtualization/virtual-machines/?name={vm_name}"
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        if data['results']:
            return data['results'][0]['id']
        else:
            print(f"VM {vm_name} not found in NetBox.")
            return None
    else:
        print(f"Failed to fetch VM ID for {vm_name}: {response.status_code} - {response.text}")
        return None

# Function to create a VM in NetBox and return its ID
def create_netbox_vm(vm_info):
    """Create VM in NetBox."""
    url = f"{netbox_url}/virtualization/virtual-machines/"
    response = requests.post(url, json=vm_info, headers=headers)

    if response.status_code == 201:
        print(f"VM {vm_info['name']} created successfully.")
        vm_data = response.json()
        print(f"Full VM creation response: {vm_data}")
        return vm_data["id"]  # Return the created VM ID
    else:
        print(f"Failed to create VM {vm_info['name']}: {response.status_code} - {response.text}")
        return None

# Function to create a network interface in NetBox
def create_netbox_interface(vm_name, vm_id):
    """Create a network interface in NetBox for a given VM."""
    # Create the network interface
    url = f"{netbox_url}/virtualization/interfaces/"
    interface_data = {
        "name": f"{vm_name}_eth0",  # Default interface name
        "virtual_machine": vm_id,  # Attach to the VM with its ID
        "type": "virtual",
    }

    response = requests.post(url, json=interface_data, headers=headers)

    if response.status_code == 201:
        print(f"Interface {interface_data['name']} created for VM {vm_name}.")
        return response.json()["id"]
    else:
        print(f"Failed to create interface {interface_data['name']}: {response.status_code} - {response.text}")
        return None

# Function to create an IP address in NetBox
def create_netbox_ip_address(ip_address, interface_id, is_primary=False):
    """Create an IP address in NetBox and assign it to an interface."""
    url = f"{netbox_url}/ipam/ip-addresses/"
    ip_data = {
        "address": ip_address,
        "status": "active",
        "assigned_object_type": "virtualization.vminterface",
        "assigned_object_id": interface_id,
        "is_primary": is_primary,
    }

    response = requests.post(url, json=ip_data, headers=headers)

    if response.status_code == 201:
        print(f"IP {ip_address} assigned to interface ID {interface_id}.")
        return response.json()["id"]
    else:
        print(f"Failed to create IP {ip_address}: {response.status_code} - {response.text}")
        return None

# Function to set the primary IP address for a VM
def set_primary_ip(vm_id, ip_id):
    """Set the primary IP address for a VM in NetBox."""
    url = f"{netbox_url}/virtualization/virtual-machines/{vm_id}/"
    vm_update_data = {
        "primary_ip4": ip_id
    }
    response = requests.patch(url, json=vm_update_data, headers=headers)
    if response.status_code == 200:
        print(f"Primary IP address set for VM ID {vm_id}.")
    else:
        print(f"Failed to set primary IP address for VM ID {vm_id}: {response.status_code} - {response.text}")

# Main script execution
if __name__ == '__main__':
    cluster_id = 57  # Use your cluster ID

    azure_vms = get_azure_vms()

    for vm in azure_vms:
        # Prepare VM payload for NetBox
        netbox_vm_info = {
            'name': vm['name'],
            'cluster': cluster_id,
            'status': 'active',
            'role': None,
            'tenant': None,
            'platform': None,
            'vcpus': vm['vcpus'],  # Use actual CPU count from Azure
            'memory': vm['memory'],  # Use actual RAM size from Azure
            'disk': vm['disk'],  # Use actual OS disk size from Azure
            'comments': f'VM ID: {vm["vm_id"]}, Location: {vm["location"]}, Type: {vm["type"]}',
        }

        # Create VM in NetBox and get VM ID
        netbox_vm_id = create_netbox_vm(netbox_vm_info)
        print(f"NetBox VM ID: {netbox_vm_id}")

        if not netbox_vm_id:
            continue  # Skip if VM creation failed

        # Add a delay to ensure the VM is fully created and indexed
        time.sleep(5)

        # Process network interfaces
        for nic_id in vm['network_interfaces']:
            network_info = get_network_info(nic_id)

            for net in network_info:
                # Create network interface in NetBox
                print(f"Creating interface for VM {vm['name']} with NetBox VM ID {netbox_vm_id}")
                interface_id = create_netbox_interface(vm['name'], netbox_vm_id)

                if interface_id:
                    if net['private_ip']:
                        ip_id = create_netbox_ip_address(net['private_ip'], interface_id, is_primary=True)
                        if ip_id:
                            set_primary_ip(netbox_vm_id, ip_id)
                    if net['public_ip']:
                        create_netbox_ip_address(net['public_ip'], interface_id)

    print("Sync process completed!")
