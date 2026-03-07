print("== xorshift linear model starter ==")

MASK = 0xffffffff

def xorshift32(x):
    x = x ^^ ((x << 13) & MASK)
    x = x ^^ (x >> 17)
    x = x ^^ ((x << 5) & MASK)
    return x & MASK

def int_to_vec(x):
    return vector(GF(2), [(x >> i) & 1 for i in range(32)])

cols = [int_to_vec(xorshift32(1 << i)) for i in range(32)]
T = Matrix(GF(2), 32, 32, lambda r, c: cols[c][r])

sample = 0x12345678
lhs = int_to_vec(xorshift32(sample))
rhs = T * int_to_vec(sample)

print(f"matrix_rank = {T.rank()}")
print(f"linear_model_matches = {lhs == rhs}")

# Use T to encode observations or solve for missing state bits over GF(2).
