import pytest
from opencrow_reversing_worker import detect_section

class DummySection:
    def __init__(self, name=None, virtual_address=None, size=None, content=None):
        if name is not None:
            self.name = name
        if virtual_address is not None:
            self.virtual_address = virtual_address
        if size is not None:
            self.size = size
        if content is not None:
            self.content = content

class DummyBinary:
    def __init__(self, sections=None):
        if sections is not None:
            self.sections = sections

def test_detect_section_normal():
    sections = [
        DummySection(name=".text", virtual_address=0x1000, size=0x1000),
        DummySection(name=".data", virtual_address=0x2000, size=0x1000)
    ]
    binary = DummyBinary(sections=sections)

    assert detect_section(binary, 0x1000) == ".text"
    assert detect_section(binary, 0x1500) == ".text"
    assert detect_section(binary, 0x1FFF) == ".text"
    assert detect_section(binary, 0x2000) == ".data"

def test_detect_section_out_of_bounds():
    sections = [
        DummySection(name=".text", virtual_address=0x1000, size=0x1000)
    ]
    binary = DummyBinary(sections=sections)

    assert detect_section(binary, 0x0FFF) is None
    assert detect_section(binary, 0x2000) is None

def test_detect_section_missing_attributes():
    # Section with missing attributes (defaults to start=0, size=0, name="")
    sections = [DummySection()]
    binary = DummyBinary(sections=sections)

    assert detect_section(binary, 0) == ""
    assert detect_section(binary, 1) is None

def test_detect_section_fallback_content_size():
    # Size is 0, should fallback to length of content
    sections = [
        DummySection(name=".rdata", virtual_address=0x3000, size=0, content=b"A"*100)
    ]
    binary = DummyBinary(sections=sections)

    assert detect_section(binary, 0x3000) == ".rdata"
    assert detect_section(binary, 0x3050) == ".rdata"
    assert detect_section(binary, 0x3064) is None # 0x3000 + 100 = 0x3064

def test_detect_section_fallback_max_size_1():
    # Size is 0, content is empty. Should fallback to max(size, 1) = 1
    sections = [
        DummySection(name=".bss", virtual_address=0x4000, size=0, content=[])
    ]
    binary = DummyBinary(sections=sections)

    assert detect_section(binary, 0x4000) == ".bss"
    assert detect_section(binary, 0x4001) is None

def test_detect_section_binary_missing_sections():
    # Binary missing sections attribute
    class EmptyBinary:
        pass

    binary = EmptyBinary()
    assert detect_section(binary, 0x1000) is None
