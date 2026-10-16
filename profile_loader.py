from config_loader import ConfigurationError, load_profile_config


ProfileError = ConfigurationError


def load_profile(profile_id):
    """Load a profile and return its legacy dictionary representation."""
    return load_profile_config(profile_id).to_mapping()
