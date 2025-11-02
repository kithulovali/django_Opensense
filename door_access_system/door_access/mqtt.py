import os
import json
import logging
import paho.mqtt.client as mqtt
from django.conf import settings
from django.core.cache import cache

# MQTT Settings
MQTT_HOST = getattr(settings, 'MQTT_HOST', '192.168.110.98')
MQTT_PORT = getattr(settings, 'MQTT_PORT', 1883)
MQTT_TOPIC = getattr(settings, 'MQTT_TOPIC', 'door/control')
MOTOR_TOPIC = getattr(settings, 'MOTOR_TOPIC', 'door/motor')

# Motor control settings
MOTOR_ACTIVATION_TIME = 2  # Time in seconds to activate the motor

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logging.info("Connected to MQTT broker")
        client.subscribe(MOTOR_TOPIC)
    else:
        logging.error(f"Failed to connect to MQTT broker with code: {rc}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        command = payload.get('command', '').lower()
        door_id = payload.get('door')
        
        if command == 'status' and door_id is not None:
            # Handle status updates from ESP32
            status = payload.get('status', {})
            cache.set(f'door_{door_id}_status', status, timeout=60)  # Cache status for 1 minute
            logging.info(f"Received status update for door {door_id}: {status}")
    
    except json.JSONDecodeError:
        logging.error("Failed to decode MQTT message")
    except Exception as e:
        logging.error(f"Error processing MQTT message: {e}")

# Initialize MQTT client
_client = None

def get_client():
    global _client
    if _client is None:
        try:
            _client = mqtt.Client()
            _client.on_connect = on_connect
            _client.on_message = on_message
            _client.connect(MQTT_HOST, MQTT_PORT, 60)
            _client.loop_start()  # Start the MQTT client loop in a background thread
        except Exception as e:
            logging.error(f"MQTT setup failed: {e}")
            _client = None
    return _client


def send_command(door_id: int, command: str):
    """
    Send a command to the door control system
    
    Args:
        door_id (int): ID of the door to control
        command (str): Command to send ('open', 'close', 'status')
    
    Returns:
        bool: True if command was sent successfully, False otherwise
    """
    payload = {
        'door': door_id,
        'command': command.lower()
    }
    
    if command.lower() == 'open':
        # For open command, also include motor activation time
        payload['duration'] = MOTOR_ACTIVATION_TIME
    
    client = get_client()
    if client is None:
        return False
        
    try:
        # Publish to the general door control topic
        result = client.publish(MOTOR_TOPIC, json.dumps(payload))
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            logging.error(f"Failed to publish MQTT message: {result.rc}")
            return False
        logging.info(f"Sent command: {command} to door {door_id}")
        return True
    except Exception as e:
        logging.error(f"MQTT publish failed: {e}")
        return False

def get_door_status(door_id: int):
    """
    Get the current status of a door
    
    Args:
        door_id (int): ID of the door
        
    Returns:
        dict: Current status of the door or None if not available
    """
    return cache.get(f'door_{door_id}_status')
