print("== MT19937 state tools starter ==")

MASK_32 = 0xffffffff

def temper(y):
    y = y ^^ (y >> 11)
    y = y ^^ ((y << 7) & 0x9d2c5680)
    y = y ^^ ((y << 15) & 0xefc60000)
    y = y ^^ (y >> 18)
    return y & MASK_32

def undo_right_shift_xor(value, shift):
    result = 0
    for bit in range(31, -1, -1):
        shifted = 0
        if bit + shift <= 31:
            shifted = (result >> (bit + shift)) & 1
        value_bit = (value >> bit) & 1
        result |= (value_bit ^^ shifted) << bit
    return result

def undo_left_shift_xor_mask(value, shift, mask):
    result = 0
    for bit in range(32):
        shifted = 0
        if bit - shift >= 0 and ((mask >> bit) & 1):
            shifted = (result >> (bit - shift)) & 1
        value_bit = (value >> bit) & 1
        result |= (value_bit ^^ shifted) << bit
    return result

def untemper(y):
    y = undo_right_shift_xor(y, 18)
    y = undo_left_shift_xor_mask(y, 15, 0xefc60000)
    y = undo_left_shift_xor_mask(y, 7, 0x9d2c5680)
    y = undo_right_shift_xor(y, 11)
    return y & MASK_32

sample = 0x12345678
tempered = temper(sample)
recovered = untemper(tempered)

print(f"tempered = {tempered}")
print(f"recovered = {recovered}")
print(f"match = {recovered == sample}")

# Apply untemper() to 624 outputs to reconstruct internal MT19937 state words.
