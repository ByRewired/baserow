# Deploying ByRewired DB

Start to finish on a fresh server, reached over a Cloudflare tunnel with
Cloudflare Access in front. Nothing here costs money on the free tiers.

The commands assume Ubuntu 22.04 or 24.04 on arm64 or amd64.

## The short way

On a fresh Ubuntu server, once you have a tunnel token from step 6:

    curl -fsSL https://raw.githubusercontent.com/ByRewired/baserow/byrewired-db/deploy/byrewired/bootstrap.sh -o bootstrap.sh
    bash bootstrap.sh

It installs Docker, adds swap when the machine is small, clones, builds the
three images, generates the keys, writes `.env` and starts everything. It asks
for the public URL and the tunnel token at the beginning and nothing after
that. Running it again is safe: the images rebuild, the data volume is left
alone.

Two things it cannot do for you, both in the Cloudflare dashboard: pointing
the tunnel hostname at `http://byrewired:80`, and adding the Access policy in
step 7. Do both.

The rest of this file is the same thing by hand, and is worth reading when
something does not work.

## 1. The server

4GB of memory is the comfortable floor to *run*. The image holds PostgreSQL,
Redis, the API, a Node process rendering the pages and a Celery worker, and
the renderer is the memory hungry one.

*Building* asks for more. Bundling the frontend needs an 8GB heap, and falling
short does not fail early with a useful message: it runs for twenty minutes
and then the kernel kills it, leaving `cannot allocate memory`. On a machine
with less, add swap to cover the gap, which is what `bootstrap.sh` does. Or
build somewhere roomier and move the image across:

    docker save byrewired/all-in-one:latest | gzip > byrewired.tar.gz
    scp byrewired.tar.gz user@server:
    ssh user@server 'gunzip -c byrewired.tar.gz | docker load'

**Oracle Cloud, always free.** Compute, Instances, Create. Pick Ubuntu, shape
`VM.Standard.A1.Flex`, and give it 2 OCPU and 12GB. That is inside the always
free allowance and does not expire. If the console answers "out of capacity",
try another availability domain, or a different region when you have not
created the tenancy yet.

**AWS, free for twelve months.** A `t3.micro` is 1GB, which is under what this
needs. If you use it, move the database to a free `db.t3.micro` RDS instance
and add swap:

    sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
    sudo mkswap /swapfile && sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

Then set `DATABASE_HOST` in step 5 and the image will use RDS instead of its
own PostgreSQL.

Leave the security group closed. The tunnel dials out, so no inbound rule is
needed, not even 80 or 443.

## 2. Docker

    sudo apt-get update
    sudo apt-get install -y ca-certificates curl git
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
      -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) \
    signed-by=/etc/apt/keyrings/docker.asc] \
    https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo \
    $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
      docker-buildx-plugin docker-compose-plugin
    sudo usermod -aG docker $USER

Log out and back in so the group applies, then check with `docker ps`.

## 3. The code

    git clone <your remote> byrewired && cd byrewired
    git checkout byrewired-db

## 4. Build the images

The all in one image is assembled from the other two, so build those first.
Expect fifteen to thirty minutes on a small instance.

    docker build -f backend/Dockerfile -t byrewired/backend:latest .
    docker build -f web-frontend/Dockerfile -t byrewired/web-frontend:latest .
    docker build -f deploy/all-in-one/Dockerfile \
      --build-arg BACKEND_IMAGE=byrewired/backend:latest \
      --build-arg WEBFRONTEND_IMAGE=byrewired/web-frontend:latest \
      -t byrewired/all-in-one:latest .

If the instance is too small to build, build on a laptop and push to a
registry, or `docker save` the image and `docker load` it on the server.

## 5. Configure

    cd deploy/byrewired
    cp env.example .env

Generate the two keys and a database password:

    openssl rand -hex 32   # SECRET_KEY
    openssl rand -hex 32   # BASEROW_JWT_SIGNING_KEY
    openssl rand -hex 16   # DATABASE_PASSWORD

`BASEROW_PUBLIC_URL` must be the address people will actually type, with
`https://` and no trailing slash. The frontend builds its asset and websocket
urls from it. Get it wrong and the site loads but nothing updates live, with
no error to tell you why.

## 6. The tunnel

In the Cloudflare dashboard pick the domain, then Zero Trust, Networks,
Tunnels, Create a tunnel, and choose Cloudflared. Copy the token into
`TUNNEL_TOKEN` in `.env`.

Add a public hostname on the tunnel:

- Subdomain and domain: whatever matches `BASEROW_PUBLIC_URL`
- Service type: HTTP
- URL: `byrewired:80`

`byrewired` is the service name on the compose network, which is how the
tunnel container reaches the app without any port being published.

## 7. Close it to the public

The tunnel authenticates nobody. Without this step anyone who learns the
hostname is in.

Zero Trust, Access, Applications, Add an application, Self hosted. Use the
same hostname. Add a policy, action Allow, and a rule such as Emails ending in
your company domain. Free for up to fifty users.

## 8. Start it

    docker compose up -d
    docker compose logs -f byrewired

The first boot runs the migrations and builds the search indexes, which takes
a few minutes. Wait for the health check:

    docker compose ps

Once `byrewired` reports healthy, open the hostname. Cloudflare Access asks
who you are, then the sign up page appears. **Create the first account
immediately** — the first one becomes staff, and leaving it open means the
first stranger through Access becomes the administrator.

## 9. Check it works

- Sign in, create a workspace, create a database and a table.
- Add a row and watch it appear in a second browser. If it does not, the
  websocket is not reaching the app, which almost always means
  `BASEROW_PUBLIC_URL` does not match the hostname.
- Open Templates from the sidebar and install one. It should import with its
  tables and rows.
- Settings, then Admin, to confirm the account is staff.

## 10. Back it up

Everything is in the `byrewired_data` volume: the PostgreSQL cluster and every
uploaded file. Dump the database on a schedule:

    docker compose exec byrewired \
      pg_dump -U baserow baserow | gzip > backup-$(date +%F).sql.gz

That covers the data but not the uploads. For a complete copy, stop the stack
and archive the whole volume:

    docker compose down
    docker run --rm -v byrewired_byrewired_data:/data -v $PWD:/backup \
      alpine tar czf /backup/byrewired-$(date +%F).tar.gz /data
    docker compose up -d

## 11. Upgrading

    git pull
    # rebuild the three images as in step 4
    docker compose up -d

Migrations run on start and there is no downgrade path, so take a backup
first.

## When something is wrong

**The page loads but nothing updates live.** `BASEROW_PUBLIC_URL` does not
match the hostname people use. Fix it and `docker compose up -d`.

**Cloudflare shows error 502.** The app is not healthy yet, or the tunnel
hostname points somewhere other than `byrewired:80`. Check
`docker compose logs byrewired`.

**The container restarts in a loop.** Almost always memory. Check
`docker stats` and `free -h`. Drop `GUNICORN_WORKERS` to 1 in `.env`, or move
to an instance with more memory.

**Signing in fails after a restart.** `BASEROW_JWT_SIGNING_KEY` changed, which
invalidates every issued token. Keep `.env` under version control somewhere
private, or in a secret manager.
