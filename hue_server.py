"""
Philips Hue Controller MCP Server

A Model Context Protocol (MCP) server that provides a comprehensive interface to control
Philips Hue smart lighting systems. This server enables AI assistants like Claude to
interact with your Hue lights using natural language.

Features:
    - Complete light control (on/off, brightness, color, temperature)
    - Group management for controlling multiple lights
    - Scene handling and custom lighting setups
    - Activity-based presets for different moods
    - Dynamic lighting effects

Requirements:
    - phue: Python library for Philips Hue API
    - mcp: Model Context Protocol Python SDK

Setup:
    1. Install dependencies: uv sync
    2. Run the server: uv run python hue_server.py
    3. Press the link button on your Hue bridge when prompted during first run
    4. Configuration is saved in ~/.hue-mcp/config.json

Usage:
    # Development/testing mode with MCP Inspector
    uv run mcp dev hue_server.py

    # Install in Claude Desktop
    uv run mcp install hue_server.py --name "Philips Hue"

    # Direct execution with stdio transport (default)
    uv run python hue_server.py

    # Run with SSE transport instead
    uv run python hue_server.py --sse

Author: Thomas Rohde
License: MIT
Version: 0.3.0
"""

import json
import logging
import os
import signal
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from phue import Bridge

# --- Configuration ---
# You can customize these values or load from a config file

# Bridge IP - can be set to None for auto-discovery
BRIDGE_IP = None  # Example: "192.168.1.100"

# Path to store bridge connection info
CONFIG_DIR = os.path.expanduser("~/.hue-mcp")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Configure logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("hue-mcp")

# --- Server Context Setup ---

@dataclass
class HueContext:
    """Context object holding the Hue bridge connection and light information cache."""
    bridge: Bridge
    light_info: dict[str, Any]  # Cache of light information

@asynccontextmanager
async def hue_lifespan(server: FastMCP) -> AsyncIterator[HueContext]:
    """
    Manage connection to Hue Bridge.

    This function handles:
    1. Discovery or connection to the bridge
    2. Storing/loading connection info
    3. Building a cache of light information
    """
    # Ensure config directory exists
    os.makedirs(CONFIG_DIR, exist_ok=True)

    # Load saved config if it exists
    bridge_ip = BRIDGE_IP
    bridge_username = None

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                config = json.load(f)
                bridge_ip = config.get('bridge_ip', bridge_ip)
                bridge_username = config.get('username')
                logger.info(f"Loaded configuration from {CONFIG_FILE}")
        except Exception as e:
            logger.error(f"Error loading config: {e}")

    # Initialize Bridge
    try:
        # If no IP specified, attempt discovery
        if not bridge_ip:
            logger.info("No bridge IP specified, attempting discovery...")
            bridge = Bridge()  # This will attempt discovery
            bridge_ip = bridge.ip
            logger.info(f"Discovered bridge at {bridge_ip}")
        else:
            logger.info(f"Connecting to bridge at {bridge_ip}")
            bridge = Bridge(bridge_ip, username=bridge_username)

        # Connect to the bridge (this may prompt user to press the link button)
        bridge.connect()

        # Save the configuration
        with open(CONFIG_FILE, 'w') as f:
            json.dump({
                'bridge_ip': bridge.ip,
                'username': bridge.username
            }, f)
            logger.info(f"Saved configuration to {CONFIG_FILE}")

        # Build a cache of light information for faster access
        light_info = bridge.get_light()

        # Initialize and yield the context
        yield HueContext(bridge=bridge, light_info=light_info)

    except Exception as e:
        logger.error(f"Error connecting to Hue bridge: {e}")
        # Re-raise to inform the server of the failure
        raise
    finally:
        # No explicit cleanup needed for bridge
        pass

# Create MCP server
mcp = FastMCP(
    "Philips Hue Controller",
    lifespan=hue_lifespan,
    dependencies=["phue"]
)

# --- Utility Functions ---

def get_bridge_ctx(ctx: Context) -> tuple[Bridge, dict[str, Any]]:
    """
    Get the Hue bridge and light info from the request context.

    Args:
        ctx: The MCP request context

    Returns:
        Tuple containing the Bridge instance and light information dictionary
    """
    hue_ctx = ctx.request_context.lifespan_context
    return hue_ctx.bridge, hue_ctx.light_info

def rgb_to_xy(r: int, g: int, b: int) -> list[float]:
    """
    Convert RGB color values to XY color space used by Philips Hue.

    The Philips Hue system uses the CIE 1931 color space, which is more accurate
    for representing colors than RGB. This function performs the conversion using
    gamma correction and the Wide RGB D65 conversion matrix.

    Args:
        r: Red value (0-255)
        g: Green value (0-255)
        b: Blue value (0-255)

    Returns:
        List containing [x, y] coordinates in the CIE color space, where both
        values are floats between 0 and 1.

    Example:
        >>> rgb_to_xy(255, 0, 0)  # Pure red
        [0.6484272236872118, 0.330856101472778]
    """
    # Normalize RGB values to 0-1 range
    r, g, b = r / 255.0, g / 255.0, b / 255.0

    # Apply gamma correction for more accurate color representation
    # Use inverse sRGB companding
    r = pow((r + 0.055) / 1.055, 2.4) if r > 0.04045 else r / 12.92
    g = pow((g + 0.055) / 1.055, 2.4) if g > 0.04045 else g / 12.92
    b = pow((b + 0.055) / 1.055, 2.4) if b > 0.04045 else b / 12.92

    # Convert to XYZ using the Wide RGB D65 conversion matrix
    X = r * 0.649926 + g * 0.103455 + b * 0.197109
    Y = r * 0.234327 + g * 0.743075 + b * 0.022598
    Z = r * 0.000000 + g * 0.053077 + b * 1.035763

    # Calculate xy values from XYZ
    sum_XYZ = X + Y + Z
    if sum_XYZ == 0:
        # Return a default value for black (0,0,0)
        return [0.0, 0.0]

    x = X / sum_XYZ
    y = Y / sum_XYZ

    return [x, y]

def resolve_light_id(light_id: int | None, light_name: str | None, light_info: dict[str, Any]) -> int | None:
    """Resolve either a light_id or a light_name to a numeric light ID.

    Args:
        light_id: Numeric ID (priority if provided and non-zero)
        light_name: Name of the light (case-insensitive partial match)
        light_info: Dictionary of light information from the bridge

    Returns:
        Resolved numeric light ID, or None if not found
    """
    if light_id:
        return light_id
    if not light_name:
        return None
    name_lower = light_name.lower()
    for lid, info in light_info.items():
        if name_lower in info.get("name", "").lower():
            return int(lid)
    return None

def validate_light_id(light_id: int, light_info: dict[str, Any]) -> bool:
    """
    Validate that a light ID exists in the light information dictionary.

    Args:
        light_id: The light ID to validate
        light_info: Dictionary of light information from the bridge

    Returns:
        True if the light ID exists, False otherwise
    """
    return str(light_id) in light_info

def validate_group_id(group_id: int, bridge: Bridge) -> bool:
    """
    Validate that a group ID exists on the Hue bridge.

    Args:
        group_id: The group ID to validate
        bridge: The Hue bridge instance

    Returns:
        True if the group ID exists, False otherwise
    """
    groups = bridge.get_group()
    return str(group_id) in groups

def format_light_info(light_info: dict[str, Any]) -> dict[str, Any]:
    """Format light information for display."""
    result = {}
    for light_id, light in light_info.items():
        # Extract the most useful information
        result[light_id] = {
            "name": light["name"],
            "on": light["state"]["on"],
            "reachable": light["state"].get("reachable", True),
            "brightness": light["state"].get("bri"),
            "color_mode": light["state"].get("colormode"),
            "type": light["type"],
            "model": light.get("modelid"),
            "manufacturer": light.get("manufacturername"),
        }
    return result

# --- Convert Resources to Tools ---

@mcp.tool()
def get_all_lights(ctx: Context) -> str:
    """
    Get information about all lights connected to the Hue bridge.

    Returns:
        JSON string containing information about all lights
    """
    bridge, light_info = get_bridge_ctx(ctx)

    # Format the light information for better readability
    formatted_info = format_light_info(light_info)

    return json.dumps(formatted_info, indent=2)

@mcp.tool()
def get_light(light_id: int, ctx: Context) -> str:
    """
    Get detailed information about a specific light.

    Args:
        light_id: The ID of the light

    Returns:
        JSON string containing detailed information about the light
    """
    bridge, light_info = get_bridge_ctx(ctx)

    try:
        # Convert light_id to string for dict lookup
        light_id_str = str(light_id)

        # Check if the light exists
        if light_id_str not in light_info:
            return f"Error: Light with ID {light_id} not found."

        return json.dumps(light_info[light_id_str], indent=2)
    except Exception as e:
        logger.error(f"Error getting light {light_id}: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def get_all_groups(ctx: Context) -> str:
    """
    Get information about all light groups.

    Returns:
        JSON string containing information about all groups
    """
    bridge, _ = get_bridge_ctx(ctx)

    try:
        groups = bridge.get_group()

        # Format the groups for better readability
        formatted_groups = {}
        for group_id, group in groups.items():
            formatted_groups[group_id] = {
                "name": group["name"],
                "type": group["type"],
                "lights": group["lights"],
                "on": group["state"]["all_on"],
                "any_on": group["state"]["any_on"]
            }

        return json.dumps(formatted_groups, indent=2)
    except Exception as e:
        logger.error(f"Error getting groups: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def get_group(group_id: int, ctx: Context) -> str:
    """
    Get information about a specific light group.

    Args:
        group_id: The ID of the group

    Returns:
        JSON string containing information about the group
    """
    bridge, _ = get_bridge_ctx(ctx)

    try:
        groups = bridge.get_group()

        # Convert group_id to string for dict lookup
        group_id_str = str(group_id)

        # Check if the group exists
        if group_id_str not in groups:
            return f"Error: Group with ID {group_id} not found."

        return json.dumps(groups[group_id_str], indent=2)
    except Exception as e:
        logger.error(f"Error getting group {group_id}: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def get_all_scenes(ctx: Context) -> str:
    """
    Get information about all scenes.

    Returns:
        JSON string containing information about all scenes
    """
    bridge, _ = get_bridge_ctx(ctx)

    try:
        scenes = bridge.get_scene()

        # Format the scenes for better readability
        formatted_scenes = {}
        for scene_id, scene in scenes.items():
            formatted_scenes[scene_id] = {
                "name": scene.get("name", "Unknown"),
                "type": scene.get("type", "Unknown"),
                "group": scene.get("group"),
                "lights": scene.get("lights", []),
                "owner": scene.get("owner")
            }

        return json.dumps(formatted_scenes, indent=2)
    except Exception as e:
        logger.error(f"Error getting scenes: {e}")
        return f"Error: {str(e)}"

# --- Tools ---

@mcp.tool()
def turn_on_light(ctx: Context, light_id: int = 0, light_name: str = "") -> str:
    """
    Turn on a specific light by ID or by name.

    Args:
        light_id: The numeric ID of the light (priority over light_name)
        light_name: The name of the light (case-insensitive partial match)

    Returns:
        Confirmation message
    """
    bridge, light_info = get_bridge_ctx(ctx)

    try:
        resolved = resolve_light_id(light_id or None, light_name or None, light_info)
        if resolved is None:
            return f"Error: Light not found (light_id={light_id}, light_name='{light_name}')."
        if not validate_light_id(resolved, light_info):
            return f"Error: Light with ID {resolved} not found."

        bridge.set_light(resolved, 'on', True)
        return f"Light {resolved} ({light_info[str(resolved)]['name']}) turned on."
    except Exception as e:
        logger.error(f"Error turning on light: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def turn_off_light(ctx: Context, light_id: int = 0, light_name: str = "") -> str:
    """
    Turn off a specific light by ID or by name.

    Args:
        light_id: The numeric ID of the light (priority over light_name)
        light_name: The name of the light (case-insensitive partial match)

    Returns:
        Confirmation message
    """
    bridge, light_info = get_bridge_ctx(ctx)

    try:
        resolved = resolve_light_id(light_id or None, light_name or None, light_info)
        if resolved is None:
            return f"Error: Light not found (light_id={light_id}, light_name='{light_name}')."
        if not validate_light_id(resolved, light_info):
            return f"Error: Light with ID {resolved} not found."

        bridge.set_light(resolved, 'on', False)
        return f"Light {resolved} ({light_info[str(resolved)]['name']}) turned off."
    except Exception as e:
        logger.error(f"Error turning off light: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def set_brightness(light_id: int, brightness: int, ctx: Context) -> str:
    """
    Set the brightness of a light.

    Args:
        light_id: The ID of the light
        brightness: Brightness level (0-254)

    Returns:
        Confirmation message
    """
    if not 0 <= brightness <= 254:
        return "Error: Brightness must be between 0 and 254."

    bridge, light_info = get_bridge_ctx(ctx)

    try:
        # Validate light ID
        if not validate_light_id(light_id, light_info):
            return f"Error: Light with ID {light_id} not found."

        # Turn on the light if it's off
        if not light_info[str(light_id)]['state']['on']:
            bridge.set_light(light_id, 'on', True)

        bridge.set_light(light_id, 'bri', brightness)

        # Calculate brightness percentage for user feedback
        percentage = round((brightness / 254) * 100)
        return f"Light {light_id} ({light_info[str(light_id)]['name']}) brightness set to {brightness} ({percentage}%)."
    except Exception as e:
        logger.error(f"Error setting brightness for light {light_id}: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def set_color_rgb(light_id: int, red: int, green: int, blue: int, ctx: Context) -> str:
    """
    Set light color using RGB values.

    Args:
        light_id: The ID of the light
        red: Red value (0-255)
        green: Green value (0-255)
        blue: Blue value (0-255)

    Returns:
        Confirmation message
    """
    if not all(0 <= c <= 255 for c in (red, green, blue)):
        return "Error: RGB values must be between 0 and 255."

    bridge, light_info = get_bridge_ctx(ctx)

    try:
        # Validate light ID
        if not validate_light_id(light_id, light_info):
            return f"Error: Light with ID {light_id} not found."

        # Check if light supports color
        if 'xy' not in light_info[str(light_id)]['state']:
            return f"Error: Light {light_id} ({light_info[str(light_id)]['name']}) does not support color."

        # Turn on the light if it's off
        if not light_info[str(light_id)]['state']['on']:
            bridge.set_light(light_id, 'on', True)

        xy = rgb_to_xy(red, green, blue)
        bridge.set_light(light_id, 'xy', xy)
        return f"Light {light_id} ({light_info[str(light_id)]['name']}) color set to RGB({red}, {green}, {blue})."
    except Exception as e:
        logger.error(f"Error setting RGB color for light {light_id}: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def set_color_temperature(light_id: int, temperature: int, ctx: Context) -> str:
    """
    Set the color temperature of a light in Kelvin.

    Color temperature controls the warmth or coolness of white light:
    - 2000K-2700K: Warm white (cozy, relaxing)
    - 3000K-4000K: Neutral white (natural daylight)
    - 5000K-6500K: Cool white (energizing, focused)

    Args:
        light_id: The ID of the light
        temperature: Color temperature in Kelvin (2000-6500)

    Returns:
        Confirmation message

    Example:
        set_color_temperature(1, 2700)  # Warm white for evening
        set_color_temperature(2, 6500)  # Cool white for working
    """
    if not 2000 <= temperature <= 6500:
        return "Error: Temperature must be between 2000K and 6500K."

    bridge, light_info = get_bridge_ctx(ctx)

    try:
        # Validate light ID
        if not validate_light_id(light_id, light_info):
            return f"Error: Light with ID {light_id} not found."

        # Check if light supports color temperature
        if 'ct' not in light_info[str(light_id)]['state']:
            return f"Error: Light {light_id} ({light_info[str(light_id)]['name']}) does not support color temperature."

        # Turn on the light if it's off
        if not light_info[str(light_id)]['state']['on']:
            bridge.set_light(light_id, 'on', True)

        # Convert temperature in Kelvin to mired (micro reciprocal degree)
        # Mired is what the Hue API uses internally
        mired = int(1000000 / temperature)
        bridge.set_light(light_id, 'ct', mired)

        return f"Light {light_id} ({light_info[str(light_id)]['name']}) color temperature set to {temperature}K."
    except Exception as e:
        logger.error(f"Error setting color temperature for light {light_id}: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def turn_on_group(ctx: Context, group_id: int = 81) -> str:
    """
    Turn on all lights in a specific group.

    Args:
        group_id: The ID of the group (default: 81 = Chambre a coucher)

    Returns:
        Confirmation message
    """
    bridge, _ = get_bridge_ctx(ctx)

    try:
        # Validate group ID
        if not validate_group_id(group_id, bridge):
            return f"Error: Group with ID {group_id} not found."

        # Get group info for name
        group_info = bridge.get_group(group_id)
        group_name = group_info.get('name', f"Group {group_id}")

        bridge.set_group(group_id, 'on', True)
        return f"Group {group_id} ({group_name}) turned on."
    except Exception as e:
        logger.error(f"Error turning on group {group_id}: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def turn_off_group(ctx: Context, group_id: int = 81) -> str:
    """
    Turn off all lights in a specific group.

    Args:
        group_id: The ID of the group (default: 81 = Chambre a coucher)

    Returns:
        Confirmation message
    """
    bridge, _ = get_bridge_ctx(ctx)

    try:
        # Validate group ID
        if not validate_group_id(group_id, bridge):
            return f"Error: Group with ID {group_id} not found."

        # Get group info for name
        group_info = bridge.get_group(group_id)
        group_name = group_info.get('name', f"Group {group_id}")

        bridge.set_group(group_id, 'on', False)
        return f"Group {group_id} ({group_name}) turned off."
    except Exception as e:
        logger.error(f"Error turning off group {group_id}: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def set_group_brightness(brightness: int, ctx: Context, group_id: int = 81) -> str:
    """
    Set the brightness of all lights in a group.

    Args:
        brightness: Brightness level (0-254)
        group_id: The ID of the group (default: 81 = Chambre a coucher)

    Returns:
        Confirmation message
    """
    if not 0 <= brightness <= 254:
        return "Error: Brightness must be between 0 and 254."

    bridge, _ = get_bridge_ctx(ctx)

    try:
        # Validate group ID
        if not validate_group_id(group_id, bridge):
            return f"Error: Group with ID {group_id} not found."

        # Get group info for name
        group_info = bridge.get_group(group_id)
        group_name = group_info.get('name', f"Group {group_id}")

        # Turn on the group if it's off
        if not group_info['state']['any_on']:
            bridge.set_group(group_id, 'on', True)

        bridge.set_group(group_id, 'bri', brightness)

        # Calculate brightness percentage for user feedback
        percentage = round((brightness / 254) * 100)
        return f"Group {group_id} ({group_name}) brightness set to {brightness} ({percentage}%)."
    except Exception as e:
        logger.error(f"Error setting brightness for group {group_id}: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def set_group_color_rgb(red: int, green: int, blue: int, ctx: Context, group_id: int = 81) -> str:
    """
    Set color for all lights in a group using RGB values.

    Args:
        red: Red value (0-255)
        green: Green value (0-255)
        blue: Blue value (0-255)
        group_id: The ID of the group (default: 81 = Chambre a coucher)

    Returns:
        Confirmation message
    """
    if not all(0 <= c <= 255 for c in (red, green, blue)):
        return "Error: RGB values must be between 0 and 255."

    bridge, _ = get_bridge_ctx(ctx)

    try:
        # Validate group ID
        if not validate_group_id(group_id, bridge):
            return f"Error: Group with ID {group_id} not found."

        # Get group info for name
        group_info = bridge.get_group(group_id)
        group_name = group_info.get('name', f"Group {group_id}")

        # Turn on the group if it's off
        if not group_info['state']['any_on']:
            bridge.set_group(group_id, 'on', True)

        xy = rgb_to_xy(red, green, blue)
        bridge.set_group(group_id, 'xy', xy)
        return f"Group {group_id} ({group_name}) color set to RGB({red}, {green}, {blue})."
    except Exception as e:
        logger.error(f"Error setting color for group {group_id}: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def set_scene(scene_id: str, ctx: Context, group_id: int = 81) -> str:
    """
    Apply a scene to a group.

    Args:
        scene_id: The ID of the scene
        group_id: The ID of the group (default: 81 = Chambre a coucher)

    Returns:
        Confirmation message
    """
    bridge, _ = get_bridge_ctx(ctx)

    try:
        # Validate group ID
        if not validate_group_id(group_id, bridge):
            return f"Error: Group with ID {group_id} not found."

        # Verify the scene exists
        scenes = bridge.get_scene()
        if scene_id not in scenes:
            return f"Error: Scene with ID {scene_id} not found."

        # Get names for better feedback
        group_name = bridge.get_group(group_id).get('name', f"Group {group_id}")
        scene_name = scenes[scene_id].get('name', f"Scene {scene_id}")

        bridge.set_group(group_id, 'scene', scene_id)
        return f"Scene '{scene_name}' applied to group '{group_name}'."
    except Exception as e:
        logger.error(f"Error applying scene {scene_id} to group {group_id}: {e}")
        return f"Error: {str(e)}"

def normalize_text(text: str) -> str:
    """Remove accents and lowercase for comparison."""
    import unicodedata
    # Normalize to decomposed form, remove combining marks, lowercase
    normalized = unicodedata.normalize('NFD', text)
    without_accents = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
    return without_accents.lower()

@mcp.tool()
def activate_scene_by_name(scene_name: str, ctx: Context, group_id: int = 81) -> str:
    """
    Find and activate a scene by its name (partial match, accent-insensitive).

    Args:
        scene_name: Name of the scene to find (case and accent insensitive, partial match)
        group_id: The ID of the group to apply the scene to (default: 81 = Chambre a coucher)

    Returns:
        Confirmation message or error if scene not found
    """
    bridge, _ = get_bridge_ctx(ctx)

    try:
        # Validate group ID
        if not validate_group_id(group_id, bridge):
            return f"Error: Group with ID {group_id} not found."

        # Search for scene by name (accent-insensitive)
        scenes = bridge.get_scene()
        search_name = normalize_text(scene_name)

        matching_scene_id = None
        matching_scene_name = None

        for sid, scene in scenes.items():
            name = scene.get('name', '')
            if search_name in normalize_text(name):
                matching_scene_id = sid
                matching_scene_name = name
                break

        if not matching_scene_id:
            # List available scenes in error message
            available = [s.get('name', 'Unknown') for s in list(scenes.values())[:10]]
            return f"Error: Scene '{scene_name}' not found. Available: {', '.join(available)}"

        # Get group name for better feedback
        group_name = bridge.get_group(group_id).get('name', f"Group {group_id}")

        # Apply the scene
        bridge.set_group(group_id, 'scene', matching_scene_id)
        return f"Scene '{matching_scene_name}' applied to group '{group_name}'."
    except Exception as e:
        logger.error(f"Error activating scene '{scene_name}': {e}")
        return f"Error: {str(e)}"

# --- Helper Tools ---

@mcp.tool()
def find_light_by_name(name: str, ctx: Context) -> str:
    """
    Find lights by searching their names.

    Args:
        name: Partial or full name to search for

    Returns:
        JSON string containing matching lights
    """
    _, light_info = get_bridge_ctx(ctx)

    try:
        # Search for lights with matching names (case-insensitive)
        name_lower = name.lower()
        matches = {}

        for light_id, light in light_info.items():
            if name_lower in light['name'].lower():
                matches[light_id] = {
                    "id": light_id,
                    "name": light['name'],
                    "type": light['type'],
                    "on": light['state']['on']
                }

        if not matches:
            return f"No lights found with name containing '{name}'."

        return json.dumps(matches, indent=2)
    except Exception as e:
        logger.error(f"Error finding lights by name '{name}': {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def create_group(
    name: str,
    light_ids: list[int],
    ctx: Context
) -> str:
    """
    Create a new group of lights.

    Args:
        name: Name for the new group
        light_ids: List of light IDs to include in the group

    Returns:
        Confirmation message with group ID
    """
    bridge, light_info = get_bridge_ctx(ctx)

    try:
        # Validate all light IDs
        invalid_lights = [lid for lid in light_ids if not validate_light_id(lid, light_info)]
        if invalid_lights:
            return f"Error: Invalid light IDs: {invalid_lights}"

        # Convert light IDs to strings (Hue API requirement)
        light_id_strings = [str(lid) for lid in light_ids]

        # Create the group
        result = bridge.create_group(name, light_id_strings)

        # Extract the group ID from the result
        if 'success' in result[0]:
            # Extract the ID from the success response
            # Format is usually: {"success":{"id":"/groups/1"}}
            success_path = list(result[0]['success'].values())[0]
            group_id = success_path.split('/')[-1]
            return f"Group '{name}' created with ID {group_id}, containing {len(light_ids)} lights."
        else:
            return f"Error creating group: {result}"
    except Exception as e:
        logger.error(f"Error creating group '{name}': {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def quick_scene(
    name: str,
    ctx: Context,
    rgb: list[int] | None = None,
    temperature: int | None = None,
    brightness: int | None = None,
    group_id: int = 0  # Default to group 0 (usually "All lights")
) -> str:
    """
    Quickly set up a lighting scene for a group.

    Args:
        name: Name for the scene
        rgb: Optional RGB values [r, g, b]
        temperature: Optional color temperature (2000-6500K)
        brightness: Optional brightness (0-254)
        group_id: Group ID to apply settings to (default: 0, usually "All lights")

    Returns:
        Confirmation message
    """
    bridge, light_info = get_bridge_ctx(ctx)

    try:
        # Validate group ID
        if not validate_group_id(group_id, bridge):
            return f"Error: Group with ID {group_id} not found."

        # Get group info for name
        group_info = bridge.get_group(group_id)
        group_name = group_info.get('name', f"Group {group_id}")

        # Turn on the group
        bridge.set_group(group_id, 'on', True)

        # Apply settings
        if brightness is not None:
            if not 0 <= brightness <= 254:
                return "Error: Brightness must be between 0 and 254."
            bridge.set_group(group_id, 'bri', brightness)

        if rgb is not None:
            if not all(0 <= c <= 255 for c in rgb) or len(rgb) != 3:
                return "Error: RGB values must be three values between 0 and 255."
            xy = rgb_to_xy(rgb[0], rgb[1], rgb[2])
            bridge.set_group(group_id, 'xy', xy)

        if temperature is not None:
            if not 2000 <= temperature <= 6500:
                return "Error: Temperature must be between 2000K and 6500K."
            # Convert temperature in K to mired
            mired = int(1000000 / temperature)
            bridge.set_group(group_id, 'ct', mired)

        # Return a summary of what was applied
        changes = []
        if brightness is not None:
            changes.append(f"brightness {brightness} ({round((brightness / 254) * 100)}%)")
        if rgb is not None:
            changes.append(f"color RGB({rgb[0]}, {rgb[1]}, {rgb[2]})")
        if temperature is not None:
            changes.append(f"temperature {temperature}K")

        return f"Scene '{name}' applied to group '{group_name}' with {', '.join(changes)}."
    except Exception as e:
        logger.error(f"Error applying quick scene '{name}': {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def refresh_lights(ctx: Context) -> str:
    """
    Refresh the light information cache.

    This is useful if lights have been added or removed, or if their state
    has changed outside this application.

    Returns:
        Information about the refreshed lights
    """
    bridge, _ = get_bridge_ctx(ctx)

    try:
        # Update the bridge's internal state
        bridge.get_api()

        # Update our cache
        light_info = bridge.get_light()
        ctx.request_context.lifespan_context.light_info = light_info

        return f"Refreshed information for {len(light_info)} lights."
    except Exception as e:
        logger.error(f"Error refreshing lights: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def set_color_preset(
    light_id: int,
    preset: str,
    ctx: Context
) -> str:
    """
    Apply a color preset to a light.

    Args:
        light_id: The ID of the light
        preset: Color preset name (warm, cool, daylight, concentration,
                relax, reading, energize, red, green, blue, purple, orange)

    Returns:
        Confirmation message
    """
    # Define color presets with RGB values
    presets = {
        # White temperature presets
        "warm": {"ct": 2500},  # Warm white (2500K)
        "cool": {"ct": 4500},  # Cool white (4500K)
        "daylight": {"ct": 6500},  # Daylight (6500K)

        # Activity presets (Philips recommended settings)
        "concentration": {"ct": 4600, "bri": 254},  # Bright cool light
        "relax": {"ct": 2700, "bri": 144},  # Warm dimmed light
        "reading": {"ct": 3200, "bri": 219},  # Moderate neutral light
        "energize": {"ct": 6000, "bri": 254},  # Bright blue light

        # Color presets
        "red": {"xy": rgb_to_xy(255, 0, 0)},
        "green": {"xy": rgb_to_xy(0, 255, 0)},
        "blue": {"xy": rgb_to_xy(0, 0, 255)},
        "purple": {"xy": rgb_to_xy(128, 0, 128)},
        "orange": {"xy": rgb_to_xy(255, 165, 0)},
    }

    if preset not in presets:
        return f"Error: Unknown preset. Available presets: {', '.join(presets.keys())}"

    bridge, light_info = get_bridge_ctx(ctx)

    try:
        # Validate light ID
        if not validate_light_id(light_id, light_info):
            return f"Error: Light with ID {light_id} not found."

        # Check capability for color temperature
        if "ct" in presets[preset] and 'ct' not in light_info[str(light_id)]['state']:
            return f"Error: Light {light_id} does not support color temperature."

        # Check capability for xy color
        if "xy" in presets[preset] and 'xy' not in light_info[str(light_id)]['state']:
            return f"Error: Light {light_id} does not support color."

        # Turn on the light if it's off
        if not light_info[str(light_id)]['state']['on']:
            bridge.set_light(light_id, 'on', True)

        # Apply preset settings
        for key, value in presets[preset].items():
            bridge.set_light(light_id, key, value)

        return f"Applied '{preset}' preset to light {light_id} ({light_info[str(light_id)]['name']})."
    except Exception as e:
        logger.error(f"Error applying preset '{preset}' to light {light_id}: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def set_group_color_preset(
    preset: str,
    ctx: Context,
    group_id: int = 81
) -> str:
    """
    Apply a color preset to a group.

    Args:
        preset: Color preset name (warm, cool, daylight, concentration,
                relax, reading, energize, red, green, blue, purple, orange)
        group_id: The ID of the group (default: 81 = Chambre a coucher)

    Returns:
        Confirmation message
    """
    # Define color presets with RGB values (same as in set_color_preset)
    presets = {
        # White temperature presets
        "warm": {"ct": 2500},  # Warm white (2500K)
        "cool": {"ct": 4500},  # Cool white (4500K)
        "daylight": {"ct": 6500},  # Daylight (6500K)

        # Activity presets (Philips recommended settings)
        "concentration": {"ct": 4600, "bri": 254},  # Bright cool light
        "relax": {"ct": 2700, "bri": 144},  # Warm dimmed light
        "reading": {"ct": 3200, "bri": 219},  # Moderate neutral light
        "energize": {"ct": 6000, "bri": 254},  # Bright blue light

        # Color presets
        "red": {"xy": rgb_to_xy(255, 0, 0)},
        "green": {"xy": rgb_to_xy(0, 255, 0)},
        "blue": {"xy": rgb_to_xy(0, 0, 255)},
        "purple": {"xy": rgb_to_xy(128, 0, 128)},
        "orange": {"xy": rgb_to_xy(255, 165, 0)},
    }

    if preset not in presets:
        return f"Error: Unknown preset. Available presets: {', '.join(presets.keys())}"

    bridge, _ = get_bridge_ctx(ctx)

    try:
        # Validate group ID
        if not validate_group_id(group_id, bridge):
            return f"Error: Group with ID {group_id} not found."

        # Get group info for name
        group_info = bridge.get_group(group_id)
        group_name = group_info.get('name', f"Group {group_id}")

        # Turn on the group if it's off
        if not group_info['state']['any_on']:
            bridge.set_group(group_id, 'on', True)

        # Apply preset settings
        for key, value in presets[preset].items():
            bridge.set_group(group_id, key, value)

        return f"Applied '{preset}' preset to group '{group_name}'."
    except Exception as e:
        logger.error(f"Error applying preset '{preset}' to group {group_id}: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def alert_light(light_id: int, ctx: Context) -> str:
    """
    Make a light flash briefly to identify it.

    Args:
        light_id: The ID of the light to alert

    Returns:
        Confirmation message
    """
    bridge, light_info = get_bridge_ctx(ctx)

    try:
        # Validate light ID
        if not validate_light_id(light_id, light_info):
            return f"Error: Light with ID {light_id} not found."

        # Use the alert feature of Hue lights
        bridge.set_light(light_id, 'alert', 'select')

        return f"Light {light_id} ({light_info[str(light_id)]['name']}) alerted with a brief flash."
    except Exception as e:
        logger.error(f"Error alerting light {light_id}: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
def set_light_effect(light_id: int, effect: str, ctx: Context) -> str:
    """
    Set a dynamic effect on a light.

    Args:
        light_id: The ID of the light
        effect: Effect type ('none' or 'colorloop')

    Returns:
        Confirmation message
    """
    # Validate effect type
    valid_effects = ['none', 'colorloop']
    if effect not in valid_effects:
        return f"Error: Effect must be one of: {', '.join(valid_effects)}"

    bridge, light_info = get_bridge_ctx(ctx)

    try:
        # Validate light ID
        if not validate_light_id(light_id, light_info):
            return f"Error: Light with ID {light_id} not found."

        # Check if light supports color (needed for effects)
        if 'xy' not in light_info[str(light_id)]['state']:
            return f"Error: Light {light_id} ({light_info[str(light_id)]['name']}) does not support color effects."

        # Turn on the light if it's off
        if not light_info[str(light_id)]['state']['on']:
            bridge.set_light(light_id, 'on', True)

        bridge.set_light(light_id, 'effect', effect)

        effect_name = "color loop" if effect == "colorloop" else "no effect"
        return f"Set {effect_name} on light {light_id} ({light_info[str(light_id)]['name']})."
    except Exception as e:
        logger.error(f"Error setting effect {effect} on light {light_id}: {e}")
        return f"Error: {str(e)}"

# --- HueBeat : controle du beat-sync Entertainment API ---

_HUE_BEAT_PY    = os.environ.get("HUE_BEAT_PATH", "/home/amineutron/dev/ironman-hue/hue_beat.py")
_HUE_BEAT_PID   = "/tmp/ironman_hue.pid"
_HUE_BEAT_CTRL  = "/tmp/lyra_hue_beat.ctrl"
_HUE_BEAT_STATE = "/tmp/lyra_hue_beat.state.json"

_VALID_PALETTES  = {"ironman", "fire", "neon", "cool", "sunset", "arctic", "auto"}
_VALID_MODES     = {"pulse", "ambiant"}


def _load_hue_env() -> dict:
    """Construit l'env pour hue_beat.py en chargeant les credentials depuis secrets.yaml."""
    env = os.environ.copy()
    secrets_path = Path.home() / "dev" / "lyra" / "secrets.yaml"
    if secrets_path.exists():
        try:
            import yaml
            with open(secrets_path) as f:
                sec = yaml.safe_load(f) or {}
            hue_sec = sec.get("hue", {})
            if hue_sec.get("beat_username"):
                env["HUE_USER"] = hue_sec["beat_username"]
            if hue_sec.get("clientkey"):
                env["HUE_CLIENTKEY"] = hue_sec["clientkey"]
            if hue_sec.get("area_id"):
                env["HUE_AREA_ID"] = hue_sec["area_id"]
        except Exception as e:
            logger.warning(f"secrets.yaml non charge: {e} -- hue_beat utilisera ses defauts")
    return env


def _beat_pid() -> int | None:
    """Retourne le PID de hue_beat si actif, None sinon."""
    try:
        with open(_HUE_BEAT_PID) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)   # signal 0 = test d'existence seulement
        return pid
    except (OSError, ValueError, FileNotFoundError):
        return None


@mcp.tool()
def hue_beat_start(mode: str = "", palette: str = "auto", bass_only: bool = True) -> str:
    """Lance hue_beat.py en arriere-plan (Entertainment API DTLS ~5ms).

    Pendant que hue_beat tourne, les commandes REST Hue sur les lumieres
    de l'area Entertainment sont suspendues (contrainte firmware Philips).

    Args:
        mode:      pulse | ambiant  (defaut: pulse si ironman, ambiant sinon)
        palette:   ironman | fire | neon | cool | sunset | arctic | auto  (defaut: auto)
        bass_only: True pour synchroniser uniquement les basses  (defaut: True)
    """
    if palette not in _VALID_PALETTES:
        return f"Erreur: palette invalide '{palette}'. Choix: {', '.join(sorted(_VALID_PALETTES))}"

    if not mode:
        mode = "pulse" if palette == "ironman" else "ambiant"
    if mode not in _VALID_MODES:
        return f"Erreur: mode invalide '{mode}'. Choix: {', '.join(_VALID_MODES)}"

    if _beat_pid() is not None:
        return "hue_beat est deja en cours. Utilisez hue_beat_stop() avant de relancer."

    if not Path(_HUE_BEAT_PY).is_file():
        return (f"hue_beat.py introuvable: {_HUE_BEAT_PY}\n"
                f"Definir HUE_BEAT_PATH dans l'environnement ou config.yaml.")

    args = [sys.executable, _HUE_BEAT_PY, f"--mode={mode}", f"--palette={palette}"]
    if bass_only:
        args.append("--bass-only")

    env = _load_hue_env()
    with open("/tmp/hue_beat.log", "w") as log:
        subprocess.Popen(args, stdout=log, stderr=log, start_new_session=True, env=env)

    # Attendre max 3s que le PID file apparaisse
    for _ in range(6):
        time.sleep(0.5)
        if _beat_pid() is not None:
            return f"hue_beat demarre (mode={mode}, palette={palette})."
    return "hue_beat lance mais PID file absent apres 3s — verifier les logs."


@mcp.tool()
def hue_beat_stop() -> str:
    """Arrete hue_beat proprement (SIGTERM → stop_entertainment → REST reprend)."""
    pid = _beat_pid()
    if pid is None:
        return "hue_beat n'est pas en cours."
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(10):
            time.sleep(0.3)
            if _beat_pid() is None:
                return f"hue_beat (PID {pid}) arrete. Mode REST Hue restaure."
        os.kill(pid, signal.SIGKILL)
        return f"hue_beat (PID {pid}) force-kill (SIGKILL) apres 3s sans reponse."
    except ProcessLookupError:
        return "hue_beat deja arrete."


@mcp.tool()
def hue_beat_status() -> str:
    """Retourne l'etat de hue_beat (actif/inactif, mode, palette, BPM)."""
    pid = _beat_pid()
    if pid is None:
        return "hue_beat: inactif."
    try:
        state = json.loads(open(_HUE_BEAT_STATE).read())
        age   = round(time.time() - state.get("ts", 0), 1)
        return (
            f"hue_beat: ACTIF (PID {pid})\n"
            f"  mode:       {state.get('mode', '?')}\n"
            f"  palette:    {state.get('palette', '?')}\n"
            f"  bpm:        {state.get('bpm', 0):.1f}\n"
            f"  beats:      {state.get('beat_count', 0)}\n"
            f"  etat age:   {age}s"
        )
    except Exception:
        return f"hue_beat: ACTIF (PID {pid}) — state file illisible."


@mcp.tool()
def hue_beat_set(palette: str = "", mode: str = "", brightness: float = -1.0,
                 floor: float = -1.0, sensitivity: float = -1.0) -> str:
    """Modifie les parametres de hue_beat a chaud (sans redemarrage).

    Args:
        palette:     ironman | fire | neon | cool | sunset | arctic | auto  (vide = inchange)
        mode:        pulse | ambiant  (vide = inchange)
        brightness:  0.1–1.0, intensite max sur les beats  (-1 = inchange)
        floor:       0.0–0.9, niveau ambiant entre les beats (-1 = inchange)
                     Ecart = brightness - floor. Plus il est grand, plus le pulse est visible.
        sensitivity: 0.5–3.0, multiplicateur de detection de beat  (-1 = inchange)
    """
    if _beat_pid() is None:
        return "hue_beat n'est pas en cours. Lancez hue_beat_start() d'abord."

    cmd: dict = {}
    if palette:
        if palette not in _VALID_PALETTES:
            return f"Erreur: palette invalide '{palette}'. Choix: {', '.join(sorted(_VALID_PALETTES))}"
        cmd["palette"] = palette
    if mode:
        if mode not in _VALID_MODES:
            return f"Erreur: mode invalide '{mode}'. Choix: {', '.join(_VALID_MODES)}"
        cmd["mode"] = mode
    if brightness >= 0:
        cmd["brightness"] = max(0.1, min(1.0, brightness))
    if floor >= 0:
        cmd["floor"] = max(0.0, min(0.9, floor))
    if sensitivity >= 0:
        cmd["sensitivity"] = max(0.5, min(3.0, sensitivity))

    if not cmd:
        return "Aucun parametre fourni. Specifiez au moins palette, mode, brightness ou sensitivity."

    tmp = _HUE_BEAT_CTRL + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cmd, f)
    os.replace(tmp, _HUE_BEAT_CTRL)

    changes = ", ".join(f"{k}={v}" for k, v in cmd.items())
    return f"Commande envoyee a hue_beat: {changes} (prise en compte sous ~500ms)."


# --- Prompts ---

@mcp.prompt()
def control_lights() -> str:
    """
    A prompt for controlling lights with natural language.
    """
    return """
You are connected to a Philips Hue lighting system. I want to control my lights using natural language.
Please help me interpret my requests and use the appropriate tools to control my lighting.

First, if needed, retrieve information about my lights using the resources: hue://lights and hue://groups.
Then, use the appropriate tools to control the lights based on my request.

For example:
- Turn on or off specific lights or groups
- Change brightness or color
- Apply presets for different activities
- Set scenes or effects

Please confirm each action you take and provide feedback on the results.
"""

@mcp.prompt()
def create_mood() -> str:
    """
    A prompt for setting up mood lighting.
    """
    return """
You are connected to my Philips Hue lighting system. I want to create mood lighting for a specific activity
or atmosphere. Please help me set up the perfect lighting environment.

First, gather information about my available lights and groups.
Then, suggest and implement a lighting setup based on my mood or activity request.

Consider:
- Appropriate brightness levels for the activity
- Color temperature or colors that match the mood
- Using preset scenes or creating custom settings
- Grouping lights appropriately

After implementing, summarize what you've done and ask if I'd like to make adjustments.
"""

@mcp.prompt()
def light_schedule() -> str:
    """
    A prompt for explaining how to set up lighting schedules.
    """
    return """
I'd like to understand how to set up scheduled lighting with my Philips Hue system.
Please explain the options available for scheduling automatic lighting changes,
including:

- Whether scheduling is handled through the Hue app rather than this interface
- The types of schedules I can create (time-based, sunrise/sunset, etc.)
- How to create routines or scenes that can be scheduled
- Any limitations I should be aware of

After explaining the scheduling capabilities, suggest some useful lighting schedules
for typical home use.
"""

# --- Main Function ---

if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Philips Hue MCP Server")
    parser.add_argument("--port", type=int, default=8080, help="Port to run the server on")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind the server to")
    parser.add_argument("--log-level", type=str, default="info",
                        choices=["debug", "info", "warning", "error", "critical"],
                        help="Logging level")
    parser.add_argument("--sse", action="store_true",
                        help="Run server using SSE transport instead of stdio (default: stdio)")
    args = parser.parse_args()

    # Set up logging level
    log_level = getattr(logging, args.log_level.upper())
    logging.getLogger("hue-mcp").setLevel(log_level)

    if args.sse:
        print(f"Starting Philips Hue MCP Server on {args.host}:{args.port}")
        print("Press Ctrl+C to stop the server")

        # Run the server using mcp.run() or manually with Uvicorn
        # mcp.run(host=args.host, port=args.port)  # Use this for direct execution

        # Or use Uvicorn for more control
        uvicorn.run(
            mcp.sse_app(),
            host=args.host,
            port=args.port,
            log_level=args.log_level
        )
    else:
        import sys
        print("Starting Philips Hue MCP Server in stdio mode", file=sys.stderr)
        print("Press Ctrl+C to stop the server", file=sys.stderr)

        mcp.run(transport='stdio')
