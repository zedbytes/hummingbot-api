"""
Patch for Hummingbot's config_helpers.py to handle missing directories
"""
import logging
from pathlib import Path

from hummingbot.client.config.config_helpers import ClientConfigAdapter


def patched_save_to_yml(yml_path: Path, cm: ClientConfigAdapter):
    """
    Patched version of save_to_yml that creates directories if they don't exist
    """
    try:
        # Ensure the parent directory exists
        yml_path.parent.mkdir(parents=True, exist_ok=True)
        
        cm_yml_str = cm.generate_yml_output_str_with_comments()
        with open(yml_path, "w", encoding="utf-8") as outfile:
            outfile.write(cm_yml_str)
    except Exception as e:
        logging.getLogger().error("Error writing configs: %s" % (str(e),), exc_info=True)


def apply_config_helpers_patch():
    """
    Apply the patch to hummingbot.client.config.config_helpers
    """
    import hummingbot.client.config.config_helpers as config_helpers
    
    # Store the original function in case we need it
    config_helpers._original_save_to_yml = config_helpers.save_to_yml
    
    # Replace with our patched version
    config_helpers.save_to_yml = patched_save_to_yml
    
    logging.info("Applied config_helpers patch: save_to_yml now creates missing directories")


def remove_config_helpers_patch():
    """
    Remove the patch and restore original functionality
    """
    import hummingbot.client.config.config_helpers as config_helpers
    
    if hasattr(config_helpers, '_original_save_to_yml'):
        config_helpers.save_to_yml = config_helpers._original_save_to_yml
        delattr(config_helpers, '_original_save_to_yml')
        logging.info("Removed config_helpers patch: restored original save_to_yml")