"""Messages returned by a DataCheck, tagged by name."""
from .data_check_message_type import DataCheckMessageType


class DataCheckMessage:
    """Base class for a message returned by a DataCheck, tagged by name.

    Args:
        message (str): Message string.
        data_check_name (str): Name of data check.
        message_code (DataCheckMessageCode): Message code associated with message. Defaults to None.
        details (dict): Additional useful information associated with the message. Defaults to None.
    """

    message_type = None

    def __init__(self, message, data_check_name, message_code=None, details=None):
        self.message = message
        self.data_check_name = data_check_name
        self.message_code = message_code
        self.details = details

    def __str__(self):
        """String representation of data check message, equivalent to self.message attribute."""
        return self.message

    def __eq__(self, other):
        """Check for equality.

        Two DataCheckMessage objs are considered equivalent if all of
        their attributes are equivalent.

        Args:
            other: An object to compare equality with.

        Returns:
            bool: True if the other object is considered an equivalent data check message, False otherwise.
        """
        return (
            self.message_type == other.message_type
            and self.message == other.message
            and self.data_check_name == other.data_check_name
            and self.message_code == other.message_code
            and self.details == other.details
        )

    def to_dict(self):
        """Return a dictionary form of the data check message."""
        message_dict = {
            "message": self.message,
            "data_check_name": self.data_check_name,
            "level": self.message_type.value,
        }
        if self.message_code is not None:
            message_dict.update({"code": self.message_code.name})
        if self.details is not None:
            message_dict.update({"details": self.details})
        return message_dict


class DataCheckError(DataCheckMessage):
    """DataCheckMessage subclass for errors returned by data checks."""

    message_type = DataCheckMessageType.ERROR
    """DataCheckMessageType.ERROR"""


class DataCheckWarning(DataCheckMessage):
    """DataCheckMessage subclass for warnings returned by data checks."""

    message_type = DataCheckMessageType.WARNING
    """DataCheckMessageType.WARNING"""
