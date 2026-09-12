# Deploying ByRewired DB on AWS

Written for somebody who has never used AWS. Every step says where to click and
why it matters.

## The shape of the problem

Two numbers drive every choice here.

**Building the frontend needs about 8GB of memory.** Bundling it is killed
partway through on anything smaller, and not quickly: it runs for twenty
minutes first. This was measured, not guessed.

**Running it needs far less**, around 2GB to be comfortable, because the build
is finished and only the server processes remain.

So the cheapest sane approach is to rent a big machine for the half hour it
takes to build, then shrink it back down to a small one to run. AWS bills by
the second, so the big half hour costs a few cents. This is the trick that
makes a free tier instance workable.

The second thing to know: **nothing needs to be reachable from the internet.**
A Cloudflare tunnel dials *out* from the server to Cloudflare, and traffic
comes back down that connection. So there are no open ports, no load balancer
and no public IP address to pay for. It is also the safest default, because a
half configured database is never exposed while you are still setting it up.

## Before you start

**Check what your account actually gets.** AWS changed the free tier in 2025.
Accounts opened before that get the old deal, twelve months of 750 hours a
month on a small instance. Newer accounts instead get credits that expire after
six months. Which one you have changes whether this is free or a few dollars a
month.

Go to the account menu, top right, then **Billing and Cost Management**, then
**Free tier** in the left sidebar. It shows what you have and how much is used.

**Set a spend alarm before anything else.** This is the step people skip and
regret. Same Billing page, **Budgets** in the sidebar, **Create budget**,
choose the **Zero spend budget** template, put in your email, create. AWS will
email you the moment anything starts costing money. It takes a minute and it is
the difference between a surprise and a notification.

## Step 1, pick a region

Top right of the console, next to your account name, is a region selector such
as *N. Virginia*. Pick the one closest to the people who will use this, because
every request travels there and back.

Everything you create lives in the region that is selected when you create it.
If your instance seems to vanish later, you are almost certainly looking at the
wrong region.

## Step 2, launch the build machine

In the search bar at the top type **EC2** and open it. EC2 is the service that
rents you a virtual machine.

Click the orange **Launch instance**.

**Name.** Something like `byrewired`. It is only a label.

**Application and OS Images.** Choose **Ubuntu**, then in the dropdown pick
**Ubuntu Server 24.04 LTS**. Ubuntu because the setup script installs packages
with `apt`, which is Ubuntu's package manager. Note whether it says *Free tier
eligible*.

**Instance type.** This is the size of the machine. Start with **t3.large**,
which has 8GB of memory. This is deliberately bigger than the free tier and
costs roughly eight cents an hour. You are renting it only for the build and
will shrink it in step 6.

**Key pair.** This is how you prove who you are when connecting. Click **Create
new key pair**, name it `byrewired`, leave RSA and `.pem` selected, and click
create. Your browser downloads a `byrewired.pem` file. **Keep it.** It cannot be
downloaded again, and without it you cannot get into the machine.

**Network settings.** Click **Edit** on the right.
- Leave *Auto-assign public IP* as **Enable**. You need it to connect over SSH.
- Under *Firewall*, choose **Create security group**.
- Tick **Allow SSH traffic from** and, in the dropdown beside it, choose **My
  IP**. This restricts connections to your current address. The default,
  anywhere, means the whole internet can try to log in, and it will.
- **Do not tick HTTP or HTTPS.** The tunnel does not need them, and leaving
  them shut means the app cannot be reached until you have deliberately put
  Cloudflare Access in front of it.

**Configure storage.** Change 8 GiB to **30 GiB**, and leave the type as gp3.
Thirty is the free tier ceiling. The images and the build cache together use
more than the default eight.

Click **Launch instance**, then **View all instances**. Wait for *Instance
state* to read **Running** and *Status check* to pass, a minute or two.

## Step 3, connect to it

Select the instance and click **Connect** at the top.

The easy way is the **EC2 Instance Connect** tab, then the **Connect** button.
It opens a terminal in the browser with no key file to handle.

The other way, from your own terminal, is the **SSH client** tab, which shows
the exact command. On a Mac, first:

    chmod 400 ~/Downloads/byrewired.pem

That tightens the file's permissions. SSH refuses to use a key that other
accounts on your machine could read, which is a reasonable thing for it to
insist on.

Then paste the command AWS showed you. It looks like:

    ssh -i ~/Downloads/byrewired.pem ubuntu@<the public address>

Answer `yes` to the fingerprint question the first time.

## Step 4, build and start it

You need a Cloudflare tunnel token first, so do **step 7** now and come back.

Then, on the server:

    curl -fsSL https://raw.githubusercontent.com/ByRewired/baserow/byrewired-db/deploy/byrewired/bootstrap.sh -o bootstrap.sh
    bash bootstrap.sh

It asks for the public URL and the tunnel token, then installs Docker, clones
the code, builds the three images and starts everything. Twenty to forty
minutes, mostly the frontend build. Leave the window open.

If your connection drops, the build dies with it. To survive that, run it
inside `screen`:

    sudo apt-get install -y screen
    screen -S build
    bash bootstrap.sh

Detach with `Ctrl-A` then `D`, and come back later with `screen -r build`.

## Step 5, reclaim the disk

The build leaves intermediate layers behind, and you are on a 30GB disk:

    docker builder prune -af
    df -h /

## Step 6, shrink the machine

This is where the saving happens. The build is done, so the memory it needed is
no longer needed.

In the EC2 console, select the instance, then:

1. **Instance state**, then **Stop instance**. Confirm. Wait for **Stopped**,
   which takes a minute. It has to be stopped to change size.
2. **Actions**, then **Instance settings**, then **Change instance type**.
3. Choose **t3.micro** if your account has the old free tier, or **t4g.small**
   for about twelve dollars a month if it does not. Click **Apply**.
4. **Instance state**, then **Start instance**.

Two things worth knowing.

**The public address changes** when you stop and start. That only affects how
you SSH in, because the tunnel dials out rather than being dialled into. Take
the new address from the console.

**t3.micro has 1GB of memory**, which is under what this wants. It runs, but
the first page load is slow because the renderer is swapping. For an internal
trial that is usually fine. If it feels bad, stop and change the type to
**t3.small**, which is 2GB and around fifteen dollars a month. Nothing is lost
by changing size, the disk and the data stay where they are.

**Only pick t4g if you are paying.** Those are ARM machines, cheaper for the
same memory, but they are not covered by the old free tier.

After it starts, log back in and check it came up:

    cd ~/byrewired/deploy/byrewired && docker compose ps

## Step 7, the Cloudflare tunnel

In the Cloudflare dashboard pick your domain, then **Zero Trust** in the
sidebar, then **Networks**, then **Tunnels**.

**Create a tunnel**, choose **Cloudflared**, name it `byrewired`, save. The next
screen shows an install command containing a long token. Copy **just the
token**, the long string after `--token`. That is what the bootstrap asks for.

Then add a **Public hostname** on the tunnel:
- *Subdomain* and *Domain*: whatever you want the address to be. It has to match
  exactly what you gave as the public URL.
- *Type*: **HTTP**
- *URL*: `byrewired:80`

`byrewired` is the name of the container on the internal Docker network. The
tunnel container reaches it directly, which is why no port is published.

## Step 8, put a lock on it

**The tunnel authenticates nobody.** Until you do this, anyone who learns or
guesses the hostname is inside your database.

**Zero Trust**, then **Access**, then **Applications**, then **Add an
application**, then **Self-hosted**.
- Give it a name and the same hostname.
- Add a policy: action **Allow**, and a rule such as *Emails ending in* with
  your company domain. Or *Emails* with an explicit list.
- Save.

Free for up to fifty users.

## Step 9, check it works

On the server, before Access is in the way:

    bash ~/byrewired/deploy/byrewired/smoke-test.sh http://localhost

It signs up, makes a workspace, a database, a table, a field and a row, then
reads the row back. Delete the workspace it leaves behind when you are done.

Then in a browser, open your hostname. Cloudflare Access asks who you are, then
the sign up page appears. **Create the first account immediately.** The first
account becomes the administrator, and until you make it, the first stranger
who gets past Access will.

Finally, open a table in two browser windows and edit a row in one. It should
change in the other within a second. If it does not, the public URL does not
match the hostname, which is the single most common thing to get wrong here.

## What this costs

With the old free tier, running a t3.micro for a month is covered, as is the
30GB disk. The build hour on a t3.large is a few cents. Data leaving AWS is
free up to 100GB a month, and an internal tool will not come close.

With the newer credits based free tier, the same setup draws down your credits
at roughly eight to ten dollars a month.

Two things that cost money quietly and are worth knowing about. An **Elastic
IP** is billed when allocated, and you do not need one here because the tunnel
dials out. **EBS snapshots** are billed per gigabyte, so delete old ones.

## Turning it off

Stopping an instance stops the compute charge but **you still pay for the
disk**. To stop paying entirely, terminate it:

EC2, select the instance, **Instance state**, **Terminate instance**. This
deletes the machine and its disk. Everything in the database goes with it, so
take a backup first:

    cd ~/byrewired/deploy/byrewired
    docker compose exec byrewired pg_dump -U baserow baserow | gzip > backup.sql.gz

then copy it to your own machine, from your machine:

    scp -i ~/Downloads/byrewired.pem ubuntu@<address>:~/byrewired/deploy/byrewired/backup.sql.gz .

## When something is wrong

**Cannot connect over SSH.** Your address changed, either because you stopped
and started the instance or because your own internet connection moved. Check
the current public address in the console, and check the security group still
allows your current IP: select the instance, **Security** tab, click the
security group, **Edit inbound rules**, set the SSH source to **My IP** again.

**The build was killed.** Out of memory. You are on too small an instance for
the build. Stop, change the type to t3.large, start, and run the bootstrap
again.

**No space left on device.** `docker builder prune -af`, and if that is not
enough, grow the disk: EC2, **Volumes**, select it, **Actions**, **Modify
volume**.

**Cloudflare shows 502.** The app is not healthy yet, or the hostname points
somewhere other than `byrewired:80`. Check with
`docker compose logs -f byrewired`.

**The page loads but nothing updates live.** The public URL does not match the
hostname. Fix it in `.env` and run `docker compose up -d`.
