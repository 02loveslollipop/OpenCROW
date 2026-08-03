print("== ECDSA partial nonce lattice starter ==")

# Toy hidden-number-style lattice for signatures where nonce bits leak.
# Replace with challenge-specific curve order n, coefficients, and bounds.
n = 10007
B = 2^8
t_values = [101, 202, 303, 404]
u_values = [505, 606, 707, 808]

dim = len(t_values) + 1
rows = []
for i in range(len(t_values)):
    row = [0] * dim
    row[i] = n
    rows.append(row)

final_row = list(t_values) + [B]
rows.append(final_row)

M = Matrix(ZZ, rows)
print(f"dimension = {M.nrows()}x{M.ncols()}")
print("lll_first_rows =")
for row in M.LLL()[:3]:
    print(row)

# Replace t_values and u_values using the standard ECDSA hidden-number relation:
# k_i = known_i + delta_i, and s_i*k_i - z_i == r_i*d (mod n)
