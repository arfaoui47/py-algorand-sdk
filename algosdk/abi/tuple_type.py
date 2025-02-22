from .base_type import ABI_LENGTH_SIZE, Type
from .bool_type import BoolType
from .. import error


class TupleType(Type):
    """
    Represents a Tuple ABI Type for encoding.

    Args:
        child_types (list): list of types in the tuple.

    Attributes:
        child_types (list)
    """

    def __init__(self, arg_types) -> None:
        if len(arg_types) >= 2 ** 16:
            raise error.ABITypeError(
                "tuple args cannot exceed a uint16: {}".format(len(arg_types))
            )
        super().__init__()
        self.child_types = arg_types

    def __eq__(self, other) -> bool:
        if not isinstance(other, TupleType):
            return False
        return self.child_types == other.child_types

    def __str__(self):
        return "({})".format(",".join(str(t) for t in self.child_types))

    def byte_len(self):
        size = 0
        i = 0
        while i < len(self.child_types):
            if isinstance(self.child_types[i], BoolType):
                after = TupleType._find_bool(self.child_types, i, 1)
                i += after
                bool_num = after + 1
                size += bool_num // 8
                if bool_num % 8 != 0:
                    size += 1
            else:
                child_byte_size = self.child_types[i].byte_len()
                size += child_byte_size
            i += 1
        return size

    def is_dynamic(self):
        return any(child.is_dynamic() for child in self.child_types)

    @staticmethod
    def _find_bool(type_list, index, delta):
        """
        Helper function to find consecutive booleans from current index in a tuple.
        """
        until = 0
        while True:
            curr = index + delta * until
            if isinstance(type_list[curr], BoolType):
                if curr != len(type_list) - 1 and delta > 0:
                    until += 1
                elif curr > 0 and delta < 0:
                    until += 1
                else:
                    break
            else:
                until -= 1
                break
        return until

    @staticmethod
    def _parse_tuple(s):
        """
        Given a tuple string, parses one layer of the tuple and returns tokens as a list.
        i.e. 'x,(y,(z))' -> ['x', '(y,(z))']
        """
        # If the tuple content is empty, return an empty list
        if not s:
            return []

        if s.startswith(",") or s.endswith(","):
            raise error.ABITypeError(
                "cannot have leading or trailing commas in {}".format(s)
            )

        if ",," in s:
            raise error.ABITypeError(
                "cannot have consecutive commas in {}".format(s)
            )

        tuple_strs = []
        depth = 0
        word = ""
        for char in s:
            word += char
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == ",":
                # If the comma is at depth 0, put the word as a new token.
                if depth == 0:
                    word = word[:-1]
                    tuple_strs.append(word)
                    word = ""
        if word:
            tuple_strs.append(word)
        if depth != 0:
            raise error.ABITypeError("parenthesis mismatch: {}".format(s))
        return tuple_strs

    @staticmethod
    def _compress_multiple_bool(value_list):
        """
        Compress consecutive boolean values into a byte for a Tuple/Array.
        """
        result = 0
        if len(value_list) > 8:
            raise error.ABIEncodingError(
                "length of list should not be greater than 8"
            )
        for i, value in enumerate(value_list):
            assert isinstance(value, bool)
            bool_val = value
            if bool_val:
                result |= 1 << (7 - i)
        return result

    def encode(self, values):
        """
        Encodes a list of values into a TupleType ABI bytestring.

        Args:
            values (list): list of values to be encoded.
            The length of the list cannot exceed a uint16.

        Returns:
            bytes: encoded bytes of the tuple
        """
        if len(self.child_types) >= (2 ** 16):
            raise error.ABIEncodingError(
                "length of tuple array should not exceed a uint16: {}".format(
                    len(self.child_types)
                )
            )
        tuple_elements = self.child_types

        # Create a head/tail component and use it to concat bytes later
        heads = list()
        tails = list()
        is_dynamic_index = list()
        i = 0
        while i < len(tuple_elements):
            element = tuple_elements[i]
            if element.is_dynamic():
                # Head is not pre-determined for dynamic types; store a placeholder for now
                heads.append(b"\x00\x00")
                is_dynamic_index.append(True)
                tail_encoding = element.encode(values[i])
                tails.append(tail_encoding)
            else:
                if isinstance(element, BoolType):
                    before = TupleType._find_bool(self.child_types, i, -1)
                    after = TupleType._find_bool(self.child_types, i, 1)

                    # Pack bytes to heads and tails
                    if before % 8 != 0:
                        raise error.ABIEncodingError(
                            "expected before index should have number of bool mod 8 equal 0"
                        )
                    after = min(7, after)
                    compressed_int = TupleType._compress_multiple_bool(
                        values[i : i + after + 1]
                    )
                    heads.append(bytes([compressed_int]))
                    i += after
                else:
                    encoded_tuple_element = element.encode(values[i])
                    heads.append(encoded_tuple_element)
                is_dynamic_index.append(False)
                tails.append(b"")
            i += 1

        # Adjust heads for dynamic types
        head_length = 0
        for head_element in heads:
            # If the element is not a placeholder, append the length of the element
            head_length += len(head_element)

        # Correctly encode dynamic types and replace placeholder
        tail_curr_length = 0
        for i in range(len(heads)):
            if is_dynamic_index[i]:
                head_value = head_length + tail_curr_length
                if head_value >= 2 ** 16:
                    raise error.ABIEncodingError(
                        "byte length {} should not exceed a uint16".format(
                            head_value
                        )
                    )
                heads[i] = head_value.to_bytes(
                    ABI_LENGTH_SIZE, byteorder="big"
                )
            tail_curr_length += len(tails[i])

        # Concatenate bytes
        return b"".join(heads) + b"".join(tails)

    def decode(self, bytestring):
        """
        Decodes a bytestring to a tuple list.

        Args:
            bytestring (bytes | bytearray): bytestring to be decoded

        Returns:
            list: values from the encoded bytestring
        """
        if not (
            isinstance(bytestring, bytes) or isinstance(bytestring, bytearray)
        ):
            raise error.ABIEncodingError(
                "value string must be in bytes: {}".format(bytestring)
            )
        tuple_elements = self.child_types
        dynamic_segments = (
            list()
        )  # Store the start and end of a dynamic element
        value_partitions = list()
        i = 0
        array_index = 0

        while i < len(tuple_elements):
            element = tuple_elements[i]
            if element.is_dynamic():
                if len(bytestring[array_index:]) < ABI_LENGTH_SIZE:
                    raise error.ABIEncodingError(
                        "malformed value: dynamically typed values must contain a two-byte length specifier"
                    )
                # Decode the size of the dynamic element
                dynamic_index = int.from_bytes(
                    bytestring[array_index : array_index + ABI_LENGTH_SIZE],
                    byteorder="big",
                    signed=False,
                )
                if len(dynamic_segments) > 0:
                    dynamic_segments[-1][1] = dynamic_index
                    # Check that the right side of segment is greater than the left side
                    assert (
                        dynamic_index
                        > dynamic_segments[len(dynamic_segments) - 1][0]
                    )
                # Since we do not know where the current dynamic element ends, put a placeholder and update later
                dynamic_segments.append([dynamic_index, -1])
                value_partitions.append(None)
                array_index += ABI_LENGTH_SIZE
            else:
                if isinstance(element, BoolType):
                    before = TupleType._find_bool(self.child_types, i, -1)
                    after = TupleType._find_bool(self.child_types, i, 1)

                    if before % 8 != 0:
                        raise error.ABIEncodingError(
                            "expected before index should have number of bool mod 8 equal 0"
                        )
                    after = min(7, after)
                    bits = int.from_bytes(
                        bytestring[array_index : array_index + 1],
                        byteorder="big",
                    )
                    # Parse bool values into multiple byte strings
                    for bool_i in range(after + 1):
                        mask = 128 >> bool_i
                        if mask & bits:
                            value_partitions.append(b"\x80")
                        else:
                            value_partitions.append(b"\x00")
                    i += after
                    array_index += 1
                else:
                    curr_len = element.byte_len()
                    value_partitions.append(
                        bytestring[array_index : array_index + curr_len]
                    )
                    array_index += curr_len
            if array_index >= len(bytestring) and i != len(tuple_elements) - 1:
                raise error.ABIEncodingError(
                    "input string is not long enough to be decoded: {}".format(
                        bytestring
                    )
                )
            i += 1

        if len(dynamic_segments) > 0:
            dynamic_segments[len(dynamic_segments) - 1][1] = len(bytestring)
            array_index = len(bytestring)
        if array_index < len(bytestring):
            raise error.ABIEncodingError(
                "input string was not fully consumed: {}".format(bytestring)
            )

        # Check dynamic element partitions
        segment_index = 0
        for i, element in enumerate(tuple_elements):
            if element.is_dynamic():
                segment_start, segment_end = dynamic_segments[segment_index]
                value_partitions[i] = bytestring[segment_start:segment_end]
                segment_index += 1

        # Decode individual tuple elements
        values = list()
        for i, element in enumerate(tuple_elements):
            val = element.decode(value_partitions[i])
            values.append(val)
        return values
