print("== MT19937 full state recovery starter ==")

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
        result |= (((value >> bit) & 1) ^^ shifted) << bit
    return result

def undo_left_shift_xor_mask(value, shift, mask):
    result = 0
    for bit in range(32):
        shifted = 0
        if bit - shift >= 0 and ((mask >> bit) & 1):
            shifted = (result >> (bit - shift)) & 1
        result |= (((value >> bit) & 1) ^^ shifted) << bit
    return result

def untemper(y):
    y = undo_right_shift_xor(y, 18)
    y = undo_left_shift_xor_mask(y, 15, 0xefc60000)
    y = undo_left_shift_xor_mask(y, 7, 0x9d2c5680)
    y = undo_right_shift_xor(y, 11)
    return y & MASK_32

# Synthetic example: 624 known state words.
state_words = [(i * 0x6c078965 + 5489) & MASK_32 for i in range(624)]
outputs = [temper(x) for x in state_words]
recovered = [untemper(y) for y in outputs]

print(f"recovered_words = {len(recovered)}")
print(f"match_prefix = {recovered[:5] == state_words[:5]}")
print(f"full_match = {recovered == state_words}")

# Replace outputs with 624 observed MT19937 outputs to recover the internal state words.
