from flask import Flask, jsonify
import requests
import os
import dotenv

app = Flask(__name__)
dotenv.load_dotenv()

def toggle_entity(entity_id, api_url, token):
    """
    Toggle a Home Assistant entity (like a light or switch).
    
    Args:
        entity_id (str): The entity ID (e.g., 'light.living_room' or 'switch.my_switch')
        api_url (str): Your Home Assistant URL (e.g., 'http://homeassistant.local:8123')
        token (str): Your Home Assistant long-lived access token
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    
    # Get current state
    state_url = f"{api_url}/api/states/{entity_id}"
    try:
        response = requests.get(state_url, headers=headers)
        response.raise_for_status()
        current_state = response.json()["state"]
        
        # Toggle the entity
        service_url = f"{api_url}/api/services/switch/toggle"
        data = {"entity_id": entity_id}
        
        response = requests.post(service_url, headers=headers, json=data)
        response.raise_for_status()
        
        return {"success": True, "message": f"Entity {entity_id} toggled from {current_state}"}
        
    except requests.exceptions.RequestException as e:
        return {"success": False, "message": f"Error toggling entity: {str(e)}"}

@app.route('/toggle', methods=['POST'])
def toggle():
    """API endpoint to toggle the switch"""
    HOME_ASSISTANT_URL = os.getenv("HOME_ASSISTANT_URL")
    ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
    ENTITY_ID = os.getenv("ENTITY_ID")
    
    result = toggle_entity(ENTITY_ID, HOME_ASSISTANT_URL, ACCESS_TOKEN)
    return jsonify(result)

@app.route('/status', methods=['GET'])
def status():
    """API endpoint to get the current status of the switch"""
    HOME_ASSISTANT_URL = os.getenv("HOME_ASSISTANT_URL")
    ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
    ENTITY_ID = os.getenv("ENTITY_ID")
    
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    
    try:
        state_url = f"{HOME_ASSISTANT_URL}/api/states/{ENTITY_ID}"
        response = requests.get(state_url, headers=headers)
        response.raise_for_status()
        current_state = response.json()
        
        return jsonify({
            "success": True,
            "state": current_state["state"],
            "attributes": current_state["attributes"]
        })
        
    except requests.exceptions.RequestException as e:
        return jsonify({
            "success": False,
            "message": f"Error getting status: {str(e)}"
        })

if __name__ == '__main__':
    app.run(port=7327)