print("== RSA starter ==")

# Replace these with challenge values.
p = 61
q = 53
e = 17
m = 42

n = p * q
phi = (p - 1) * (q - 1)
d = inverse_mod(e, phi)
c = power_mod(m, e, n)
m2 = power_mod(c, d, n)

print(f"n = {n}")
print(f"phi = {phi}")
print(f"d = {d}")
print(f"ciphertext = {c}")
print(f"decrypted = {m2}")

# Example CRT recombination pattern.
dp = d % (p - 1)
dq = d % (q - 1)
qinv = inverse_mod(q, p)
m1 = power_mod(c, dp, p)
m2p = power_mod(c, dq, q)
h = (qinv * (m1 - m2p)) % p
m_crt = m2p + h * q
print(f"crt_decrypted = {m_crt}")
