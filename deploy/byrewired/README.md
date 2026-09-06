# Deploying ByRewired DB

A single host running the all in one image, reached through a Cloudflare
tunnel. No inbound port is opened and no load balancer is involved, which is
what keeps an internal deployment free to run.

## What the host needs

4GB of memory is the comfortable floor. The image runs PostgreSQL, Redis, the
Django API, a Nuxt server rendering process and a Celery worker, and the
renderer is the memory hungry one. It will start on 1GB with swap and the
worker counts dropped to one, but the first paint is slow enough to be
noticeable in a demonstration.

Anything that can run Docker works. Oracle Cloud's always free ARM instances
are the most generous option, and the images are built for arm64 as well as
amd64.

## Build and publish the images

The all in one image is assembled from the backend and web frontend images, so
build those first. From the repository root:

    docker build -f backend/Dockerfile -t byrewired/backend:latest .
    docker build -f web-frontend/Dockerfile -t byrewired/web-frontend:latest .
    docker build -f deploy/all-in-one/Dockerfile \
      --build-arg BACKEND_IMAGE=byrewired/backend:latest \
      --build-arg WEBFRONTEND_IMAGE=byrewired/web-frontend:latest \
      -t byrewired/all-in-one:latest .

Push the result to whichever registry the host can read, or build on the host
itself and skip the registry.

## Set up the tunnel

In the Cloudflare Zero Trust dashboard, under Networks then Tunnels, create a
tunnel and copy its token. Add a public hostname pointing at
`http://byrewired:80`, which is the service name on the compose network.

Under Access then Applications, add a self hosted application for the same
hostname and a policy allowing the people who should get in. Up to fifty users
costs nothing. Without this the app is reachable by anyone who learns the
hostname, since the tunnel itself does no authentication.

## Run it

    cp env.example .env
    # fill in .env, then
    docker compose up -d

The first boot runs migrations and builds the search indexes, so the health
check is given four minutes before it starts failing. Watch it with
`docker compose logs -f byrewired`.

## Back it up

Everything that matters is in the `byrewired_data` volume: the Postgres
cluster and every uploaded file. Snapshot it on a schedule.

    docker compose exec byrewired \
      pg_dump -U baserow baserow | gzip > backup-$(date +%F).sql.gz

That covers the database but not uploads. For a complete copy, stop the stack
and archive the volume.

## Upgrading

Pull or rebuild the image, then `docker compose up -d`. Migrations run on
start. Take a backup first, since there is no downgrade path.
