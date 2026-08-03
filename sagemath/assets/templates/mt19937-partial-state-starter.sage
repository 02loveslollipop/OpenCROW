print("== MT19937 partial-state starter ==")

MASK_32 = 0xffffffff

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

def apply_known_mask(value, known_mask):
    bits = []
    for i in range(32):
        if (known_mask >> i) & 1:
            bits.append((value >> i) & 1)
        else:
            bits.append(None)
    return bits

tempered_outputs = [
    729696813,
    3759217314,
]

known_mask = 0xffff0000

state_words = [untemper(v) for v in tempered_outputs]
for idx, word in enumerate(state_words):
    visible = apply_known_mask(word, known_mask)
    known_count = len([b for b in visible if b is not None])
    print(f"state[{idx}] = {word}")
    print(f"known_bits[{idx}] = {known_count}")

# Extend this by collecting 624 outputs, untempering them, and solving for
# missing bits or validating candidate states against future outputs.
