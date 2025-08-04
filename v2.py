import discord
from discord.ext import commands
import asyncio
import uuid
import random
import string
import time
from datetime import datetime, timedelta
import subprocess
import os

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Storage and database file
DATABASE_FILE = 'database.txt'
admin_ids = {}  # Replace with actual admin IDs
vps_data = {}
token = ""
uptime_data = {}

# Load data from database.txt
def load_database():
    global vps_data, uptime_data
    if os.path.exists(DATABASE_FILE):
        with open(DATABASE_FILE, 'r') as f:
            for line in f:
                if line.strip():
                    vps_id, owner_id, memory, cpu, username, ssh, status, created_at, expiry = line.strip().split('\t')
                    vps_data[vps_id] = {
                        'owner_id': int(owner_id),
                        'memory': memory,
                        'cpu': cpu,
                        'username': username,
                        'full_ssh': ssh,
                        'status': status,
                        'created_at': created_at,
                        'expiry': expiry if expiry != 'None' else None
                    }
                    uptime_data[vps_id] = time.time()  # Initialize uptime on load

# Save data to database.txt
def save_database():
    with open(DATABASE_FILE, 'w') as f:
        for vps_id, data in vps_data.items():
            line = f"{vps_id}\t{data['owner_id']}\t{data['memory']}\t{data['cpu']}\t{data['username']}\t{data['full_ssh']}\t{data['status']}\t{data['created_at']}\t{data['expiry'] or 'None'}\n"
            f.write(line)

# OS Selection View
class OSSelectView(discord.ui.View):
    def __init__(self, ctx, memory, cpu, username, expiry=None):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.memory = memory
        self.cpu = cpu
        self.username = username
        self.expiry = expiry

        select = discord.ui.Select(
            placeholder="Select an operating system",
            options=[
                discord.SelectOption(label="Ubuntu 22.04", value="ubuntu-22.04"),
                discord.SelectOption(label="Debian 12", value="debian-12")
            ]
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        os_type = interaction.data["values"][0]
        await interaction.response.defer()
        await create_vps_with_os(self.ctx, os_type, self.memory, self.cpu, self.username, self.expiry)

async def create_vps_with_os(ctx, os_type, memory, cpu, username, expiry=None):
    if ctx.author.id not in admin_ids:
        await ctx.send("Only admins can create VPS.")
        return

    if not os.path.exists(DOCKERFILE_PATH):
        await ctx.send("Dockerfile not found. Ensure Dockerfile (2).txt exists.")
        return

    vps_id = str(uuid.uuid4())[:8].upper()
    token = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    ssh_pass = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    container_name = f"vps_{vps_id}"

    try:
        subprocess.run([
            "docker", "build", "-t", container_name,
            "-f", DOCKERFILE_PATH, "."
        ], check=True)
        subprocess.run([
            "docker", "run", "-d", "--name", container_name,
            f"--memory={memory}g", f"--cpus={cpu}",
            "--privileged", "--cap-add=ALL"
        ], check=True)
        await asyncio.sleep(10)  # Wait for container initialization
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", container_name, "tmate", "-F",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        ssh_command = await capture_ssh_session_line(proc)
        if not ssh_command:
            raise Exception("Failed to generate SSH session. Ensure tmate is running.")
    except subprocess.CalledProcessError as e:
        await ctx.send(f"Error creating VPS: {e}")
        cleanup_container(container_name)
        return

    vps_data[vps_id] = {
        'owner_id': ctx.author.id,
        'memory': memory,
        'cpu': cpu,
        'username': username,
        'full_ssh': ssh_command or f"ssh {username}@vps.firecloud.com",
        'status': 'Running',
        'created_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S IST', timedelta(hours=5.5)),
        'expiry': expiry
    }
    uptime_data[vps_id] = time.time()
    save_database()

    dm_message = f"VPS Creation Successful!\nVPS ID: {vps_id}\nToken: {token}\nMemory: {memory}\nCPU: {cpu}\nUsername: {username}\nSSH: {ssh_command or 'N/A'}\nFull SSH: {vps_data[vps_id]['full_ssh']}\nOS: {os_type}\nExpiry: {expiry or 'None'}\nCreated: {vps_data[vps_id]['created_at']}"
    try:
        await ctx.author.send(dm_message)
        await ctx.send(f"VPS created for {ctx.author.mention}. Check your DMs for details.")
    except discord.Forbidden:
        await ctx.send(f"VPS created, but unable to send DM to {ctx.author.mention}. Enable DMs or check permissions.")

@bot.command()
async def create_vps(ctx, memory: str, cpu: str, username: str, expiry: str = None):
    if ctx.author.id not in admin_ids:
        await ctx.send("Only admins can create VPS.")
        return
    expiry_seconds = parse_time_to_seconds(expiry) if expiry else None
    expiry_date = format_expiry_date(expiry_seconds) if expiry_seconds else None
    await ctx.send("Select an OS for your VPS:", view=OSSelectView(ctx, memory, cpu, username, expiry_date))

def parse_time_to_seconds(time_str):
    units = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'M': 2592000, 'y': 31536000}
    if time_str and time_str[-1] in units and time_str[:-1].isdigit():
        return int(time_str[:-1]) * units[time_str[-1]]
    return None

def format_expiry_date(seconds):
    if seconds:
        return (datetime.utcnow() + timedelta(seconds=seconds) + timedelta(hours=5.5)).strftime('%Y-%m-%d %H:%M:%S IST')
    return None

async def capture_ssh_session_line(process):
    start_time = time.time()
    while time.time() - start_time < 30:
        output = await process.stdout.readline()
        if not output:
            break
        output = output.decode('utf-8').strip()
        if "ssh session:" in output:
            return output.split("ssh session:")[1].strip()
        await asyncio.sleep(1)
    return None

def cleanup_container(container_name):
    subprocess.run(["docker", "stop", container_name], check=False)
    subprocess.run(["docker", "rm", container_name], check=False)

@bot.command()
async def manage_vps(ctx, vps_id: str, action: str = None, os_type: str = None):
    if vps_id not in vps_data or vps_data[vps_id]['owner_id'] != ctx.author.id:
        await ctx.send("Invalid VPS ID or you do not own this VPS.")
        return

    container_name = vps_data[vps_id]['container_name']
    if action is None:
        await ctx.send("Options: Start | Stop | Restart | Status | Reinstall")
        return

    if action.lower() == 'start':
        try:
            subprocess.run(["docker", "start", container_name], check=True)
            vps_data[vps_id]['status'] = 'Running'
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", container_name, "tmate", "-F",
                stdout=asyncio.subprocess.PIPE
            )
            ssh_command = await capture_ssh_session_line(proc)
            vps_data[vps_id]['full_ssh'] = ssh_command or vps_data[vps_id]['full_ssh']
            save_database()
            await ctx.send(f"VPS {vps_id} started. SSH: {ssh_command or 'N/A'}")
        except subprocess.CalledProcessError as e:
            await ctx.send(f"Error: {e}")
    elif action.lower() == 'stop':
        try:
            subprocess.run(["docker", "stop", container_name], check=True)
            vps_data[vps_id]['status'] = 'Offline'
            save_database()
            await ctx.send(f"VPS {vps_id} stopped.")
        except subprocess.CalledProcessError as e:
            await ctx.send(f"Error: {e}")
    elif action.lower() == 'restart':
        try:
            subprocess.run(["docker", "restart", container_name], check=True)
            vps_data[vps_id]['status'] = 'Running'
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", container_name, "tmate", "-F",
                stdout=asyncio.subprocess.PIPE
            )
            ssh_command = await capture_ssh_session_line(proc)
            vps_data[vps_id]['full_ssh'] = ssh_command or vps_data[vps_id]['full_ssh']
            save_database()
            await ctx.send(f"VPS {vps_id} restarted. SSH: {ssh_command or 'N/A'}")
        except subprocess.CalledProcessError as e:
            await ctx.send(f"Error: {e}")
    elif action.lower() == 'status':
        try:
            result = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", container_name], capture_output=True, text=True, check=True)
            status = "🟢 Running" if result.stdout.strip() == "true" else "🔴 Stopped"
            await ctx.send(f"VPS {vps_id} Status: {status}")
        except subprocess.CalledProcessError as e:
            await ctx.send(f"Error: {e}")
    elif action.lower() == 'reinstall':
        if os.path.exists(DOCKERFILE_PATH):
            try:
                subprocess.run(["docker", "stop", container_name], check=True)
                subprocess.run(["docker", "rm", container_name], check=True)
                subprocess.run([
                    "docker", "build", "-t", container_name,
                    "-f", DOCKERFILE_PATH, "."
                ], check=True)
                subprocess.run([
                    "docker", "run", "-d", "--name", container_name,
                    f"--memory={vps_data[vps_id]['memory']}g", f"--cpus={vps_data[vps_id]['cpu']}",
                    "--privileged", "--cap-add=ALL"
                ], check=True)
                vps_data[vps_id]['os_type'] = 'ubuntu-22.04'
                proc = await asyncio.create_subprocess_exec(
                    "docker", "exec", container_name, "tmate", "-F",
                    stdout=asyncio.subprocess.PIPE
                )
                ssh_command = await capture_ssh_session_line(proc)
                vps_data[vps_id]['full_ssh'] = ssh_command or vps_data[vps_id]['full_ssh']
                save_database()
                await ctx.send(f"VPS {vps_id} reinstalled. SSH: {ssh_command or 'N/A'}")
            except subprocess.CalledProcessError as e:
                await ctx.send(f"Error: {e}")
        else:
            await ctx.send("Dockerfile not found.")

@bot.command()
async def recreate_vps(ctx, old_vps_id: str):
    if ctx.author.id not in admin_ids:
        await ctx.send("Only admins can use this command.")
        return
    if old_vps_id not in vps_data:
        await ctx.send("Invalid VPS ID.")
        return

    new_vps_id = str(uuid.uuid4())[:8].upper()
    new_ssh_pass = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    old_container = vps_data[old_vps_id]['container_name']
    new_container = f"vps_{new_vps_id}"

    try:
        subprocess.run(["docker", "stop", old_container], check=True)
        subprocess.run(["docker", "rm", old_container], check=True)
        subprocess.run([
            "docker", "build", "-t", new_container,
            "-f", DOCKERFILE_PATH, "."
        ], check=True)
        subprocess.run([
            "docker", "run", "-d", "--name", new_container,
            f"--memory={vps_data[old_vps_id]['memory']}g", f"--cpus={vps_data[old_vps_id]['cpu']}",
            "--privileged", "--cap-add=ALL"
        ], check=True)
        await asyncio.sleep(10)  # Wait for container initialization
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", new_container, "tmate", "-F",
            stdout=asyncio.subprocess.PIPE
        )
        ssh_command = await capture_ssh_session_line(proc)
        if not ssh_command:
            raise Exception("Failed to generate SSH session")
    except subprocess.CalledProcessError as e:
        await ctx.send(f"Error recreating VPS: {e}")
        cleanup_container(new_container)
        return

    vps_data[new_vps_id] = vps_data[old_vps_id].copy()
    vps_data[new_vps_id].update({
        'vps_id': new_vps_id,
        'ssh_pass': new_ssh_pass,
        'full_ssh': ssh_command or vps_data[old_vps_id]['full_ssh'],
        'container_name': new_container,
        'created_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S IST', timedelta(hours=5.5))
    })
    del vps_data[old_vps_id]
    save_database()

    dm_message = f"VPS Recreated!\nNew VPS ID: {new_vps_id}\nUsername: {vps_data[new_vps_id]['username']}\nSSH: {ssh_command}\nFull SSH: {vps_data[new_vps_id]['full_ssh']}\nCreated: {vps_data[new_vps_id]['created_at']}"
    try:
        await ctx.author.send(dm_message)
        await ctx.send(f"VPS {old_vps_id} recreated as {new_vps_id}. Check your DMs.")
    except discord.Forbidden:
        await ctx.send(f"VPS recreated, but unable to send DM to {ctx.author.mention}. Enable DMs or check permissions.")

@bot.command()
async def nodes(ctx):
    user_id = ctx.author.id
    if str(user_id) not in vps_data:
        await ctx.send("No VPS instances found for you.")
        return
    end_time = time.time() + 30
    while time.time() < end_time:
        message = "Node Status\n"
        for vps_id, data in vps_data.items():
            if data['owner_id'] == user_id:
                uptime = int(time.time() - uptime_data[vps_id])
                try:
                    stats = subprocess.run(["docker", "stats", data['container_name'], "--no-stream", "--format", "{{.MemUsage}} {{.CPUPerc}}"], capture_output=True, text=True, check=True)
                    mem, cpu = stats.stdout.strip().split()
                    status = "🟢 Running" if subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", data['container_name']], capture_output=True, text=True).stdout.strip() == "true" else "🔴 Stopped"
                except subprocess.CalledProcessError:
                    mem, cpu, status = "N/A", "N/A", "🔴 Stopped"
                message += f"VPS {vps_id}: Status: {status}, RAM: {mem}, CPU: {cpu}%, Uptime: {uptime}s\n"
        await ctx.send(message)
        await asyncio.sleep(1)
        message = "Node Status\n"
    await ctx.send("Node status update completed.")

@bot.command()
async def send_vps(ctx, user_id: int, username: str, ssh_pass: str):
    if ctx.author.id not in admin_ids:
        await ctx.send("Only admins can use this command.")
        return
    user = bot.get_user(user_id)
    if not user:
        await ctx.send("Invalid user ID.")
        return
    vps_info = next((data for vps_id, data in vps_data.items() if data['owner_id'] == user_id), {})
    dm_message = f"VPS Details:\nUsername: {username}\nSSH Password: {ssh_pass}\nFull SSH: {vps_info.get('full_ssh', 'N/A')}"
    try:
        await user.send(dm_message)
        await ctx.send(f"VPS details sent to user ID {user_id}.")
    except discord.Forbidden:
        await ctx.send(f"Unable to send DM to user ID {user_id}. Enable DMs or check permissions.")

@bot.command()
async def addadmin_bot(ctx, user_id: int):
    if ctx.author.id not in admin_ids:
        await ctx.send("Only admins can use this command.")
        return
    admin_ids.add(user_id)
    await ctx.send(f"User ID {user_id} added as admin.")

@bot.command()
async def delete_vps(ctx, vps_id: str, username: str):
    if vps_id not in vps_data or vps_data[vps_id]['owner_id'] != ctx.author.id:
        await ctx.send("Invalid VPS ID or you do not own this VPS.")
        return
    if vps_data[vps_id]['username'] != username:
        await ctx.send("Incorrect username.")
        return
    try:
        container_name = vps_data[vps_id]['container_name']
        subprocess.run(["docker", "stop", container_name], check=True)
        subprocess.run(["docker", "rm", container_name], check=True)
        del vps_data[vps_id]
        del uptime_data[vps_id]
        save_database()
        await ctx.send(f"VPS {vps_id} deleted successfully.")
    except subprocess.CalledProcessError as e:
        await ctx.send(f"Error deleting VPS: {e}")

@bot.command()
async def vpslist(ctx):
    user_id = ctx.author.id
    vps_list = [vps_id for vps_id, data in vps_data.items() if data['owner_id'] == user_id]
    if not vps_list:
        await ctx.send("No VPS instances found.")
        return
    message = "Your VPS Instances\n"
    for vps_id in vps_list:
        data = vps_data[vps_id]
        message += f"VPS {vps_id}\nOwner: {ctx.author.name}\nStatus: {data['status']}\nMemory: {data['memory']}\nCPU: {data['cpu']}\nUsername: {data['username']}\nOS: {data.get('os_type', 'ubuntu-22.04')}\nCreated: {data['created_at']}\n"
    await ctx.send(message + f"Total VPS: {len(vps_list)}")

@bot.event
async def on_ready():
    load_database()
    print(f'Bot is ready as {bot.user}')

  bot.run(token)  # Replace with your bot token
