import os
import discord
import asyncio

from dotenv import load_dotenv
from discord import app_commands
from Gears.Ids import CMusic, CDiscord
load_dotenv()

Client_secret = os.getenv('CLIENT_SECRET')
Refresh_token = os.getenv('REFRESH_TOKEN')

from Functions.Music import spotifier
#Start bot
TOKEN = os.getenv('Token')
intents = discord.Intents.default()
bot = discord.Client(intents=intents)
Guild = discord.Object(id=CDiscord)
tree = app_commands.CommandTree(bot)



#Bot Functionalities
@bot.event
async def on_message(message):
  if message.author == bot.user:
    return
  if message.channel == bot.get_channel(CMusic):
    bot_message = await message.channel.send(
      "Don't send that here. \n Only music commands, thanks.")
    await message.delete()
    await asyncio.sleep(3)
    await bot_message.delete()


async def Incorrect_channel(ctx):
  await ctx.response.send_message('Inccorect channel for that')
  await asyncio.sleep(3)
  await ctx.delete_original_response()


#Bot commands
@tree.command(name="get_playlist",
              description="Download a spotify playlist",
              guild=Guild)
async def DSpotify(ctx, url: str):
  if ctx.channel == bot.get_channel(CMusic):
    await spotifier.set_up(ctx, url, bot)
  else:
    await Incorrect_channel(ctx)


if __name__ == '__main__':
  bot.run(TOKEN)