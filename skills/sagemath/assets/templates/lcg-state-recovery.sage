print("== LCG state recovery starter ==")

modulus = 2^31
a_real = 1103515245
c_real = 12345
seed = 1337

def lcg_step(x, a, c, m):
    return (a * x + c) % m

x0 = seed
x1 = lcg_step(x0, a_real, c_real, modulus)
x2 = lcg_step(x1, a_real, c_real, modulus)
x3 = lcg_step(x2, a_real, c_real, modulus)

a = ((x2 - x1) * inverse_mod(x1 - x0, modulus)) % modulus
c = (x1 - a * x0) % modulus
x4 = lcg_step(x3, a, c, modulus)

print(f"recovered_a = {a}")
print(f"recovered_c = {c}")
print(f"next_state = {x4}")

# Replace x0..x3 with observed states or adapt this to partial-output recovery.
