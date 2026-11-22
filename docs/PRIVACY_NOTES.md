# Privacy (technical)

Logs carry user_id only. Passwords are hashed with argon2id; legacy SHA-256
password hashes are rehashed on successful login. Account deletion removes the
user, refresh tokens, password resets, jobs, backtests, usage rows and the
user's uploaded CSV directory. Export via history endpoints. Audit table
reserved.
