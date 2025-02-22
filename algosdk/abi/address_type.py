from .base_type import Type
from .byte_type import ByteType
from .tuple_type import TupleType
from .. import error

from algosdk import encoding


class AddressType(Type):
    """
    Represents an Address ABI Type for encoding.
    """

    def __init__(self) -> None:
        super().__init__()

    def __eq__(self, other) -> bool:
        if not isinstance(other, AddressType):
            return False
        return True

    def __str__(self):
        return "address"

    def byte_len(self):
        return 32

    def is_dynamic(self):
        return False

    def _to_tuple_type(self):
        child_type_array = list()
        for _ in range(self.byte_len()):
            child_type_array.append(ByteType())
        return TupleType(child_type_array)

    def encode(self, value):
        """
        Encode an address string or a 32-byte public key into a Address ABI bytestring.

        Args:
            value (str | bytes): value to be encoded. It can be either a base32
            address string or a 32-byte public key.

        Returns:
            bytes: encoded bytes of the address
        """
        # Check that the value is an address in string or the public key in bytes
        if isinstance(value, str):
            try:
                value = encoding.decode_address(value)
            except Exception as e:
                raise error.ABIEncodingError(
                    "cannot encode the following address: {}".format(value)
                ) from e
        elif (
            not (isinstance(value, bytes) or isinstance(value, bytearray))
            or len(value) != 32
        ):
            raise error.ABIEncodingError(
                "cannot encode the following public key: {}".format(value)
            )
        return bytes(value)

    def decode(self, bytestring):
        """
        Decodes a bytestring to a base32 encoded address string.

        Args:
            bytestring (bytes | bytearray): bytestring to be decoded

        Returns:
            str: base32 encoded address from the encoded bytestring
        """
        if (
            not (
                isinstance(bytestring, bytearray)
                or isinstance(bytestring, bytes)
            )
            or len(bytestring) != 32
        ):
            raise error.ABIEncodingError(
                "address string must be in bytes and correspond to a byte[32]: {}".format(
                    bytestring
                )
            )
        # Return the base32 encoded address string
        return encoding.encode_address(bytestring)
