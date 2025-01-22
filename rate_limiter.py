from slowapi import Limiter
from slowapi.util import get_remote_address

def create_rate_limiter():

    limiter = Limiter(key_func=get_remote_address, default_limits=["100/5seconds"])
    return limiter

rate_limiter = create_rate_limiter()
