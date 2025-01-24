
## TimescaleDB
```CREATE EXTENSION IF NOT EXISTS timescaledb;```

```SELECT create_hypertable('live_track_points', 'datetime', chunk_time_interval => INTERVAL '1 day');
SELECT create_hypertable('uploaded_track_points', 'datetime', chunk_time_interval => INTERVAL '1 day');```


-- For live_track_points
```GRANT ALL PRIVILEGES ON TABLE live_track_points TO py_ll_user;
GRANT ALL PRIVILEGES ON TABLE uploaded_track_points TO py_ll_user;
GRANT ALL PRIVILEGES ON TABLE flights TO py_ll_user;```

-- Common privileges needed for both tables
```GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO py_ll_user;
GRANT USAGE ON SCHEMA public TO py_ll_user;```

-- DELETE ALL
DELETE FROM public.live_track_points;
DELETE FROM public.upload_track_points;
DELETE FROM public.flights;



## Working with Alembic
Run `alembic init alembic`
Then `alembic revision -m "description of the migration" --autogenerate`
Finally `alembic upgrade head`