print("== ECDSA nonce reuse starter ==")

# Two signatures with the same nonce k satisfy:
# s1 = k^-1 (z1 + r*d) mod n
# s2 = k^-1 (z2 + r*d) mod n
# Recover:
# k = (z1 - z2) / (s1 - s2) mod n
# d = (s1*k - z1) / r mod n

n = 10177
r = 1337
s1 = 4242
s2 = 3131
z1 = 1234
z2 = 5678

if gcd(s1 - s2, n) != 1 or gcd(r, n) != 1:
    print("Parameters are not invertible modulo n; replace the toy values.")
else:
    k = ((z1 - z2) * inverse_mod(s1 - s2, n)) % n
    d = ((s1 * k - z1) * inverse_mod(r, n)) % n
    print(f"k = {k}")
    print(f"d = {d}")

# Replace n, r, s1, s2, z1, z2 with real challenge values.
