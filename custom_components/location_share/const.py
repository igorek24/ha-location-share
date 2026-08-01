"""Constants for the Location Share integration."""

DOMAIN = "location_share"

CONF_ENTITIES = "entities"
CONF_BASE_URL = "base_url"
CONF_HOME_ZONE = "home_zone"
CONF_DEFAULT_MINUTES = "default_share_minutes"
CONF_DEFAULT_SPEED_KMH = "default_speed_kmh"

DEFAULT_HOME_ZONE = "zone.home"
DEFAULT_MINUTES = 60
DEFAULT_SPEED_KMH = 40
MIN_MINUTES = 5
MAX_MINUTES = 60 * 24 * 7          # a week

SERVICE_CREATE_SHARE = "create_share"
SERVICE_REVOKE_SHARE = "revoke_share"
SERVICE_REVOKE_ALL = "revoke_all_shares"
SERVICE_ON_MY_WAY = "on_my_way"

ATTR_ENTITY = "entity_id"
ATTR_MINUTES = "minutes"
ATTR_LABEL = "label"
ATTR_PRECISION = "precision"
ATTR_TOKEN = "token"
ATTR_NOTIFY = "notify_target"
ATTR_MESSAGE = "message"
ATTR_INCLUDE_LINK = "include_link"

EVENT_SHARE_CREATED = "location_share_created"
EVENT_SHARE_VIEWED = "location_share_viewed"

UPDATE_SIGNAL = "location_share_update"
