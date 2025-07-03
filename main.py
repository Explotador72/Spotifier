import threading
import bot_Function

bot_thread = threading.Thread(target=bot_Function.bot.run, args=(bot_Function.TOKEN,))
bot_thread.start()

bot_thread.join()
