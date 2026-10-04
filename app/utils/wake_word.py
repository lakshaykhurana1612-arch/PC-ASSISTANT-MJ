from app.utils.voice import listen_wake, speak
import keyboard

def wake_word_loop():

    while True:

        # Break wake listener
        if keyboard.is_pressed("esc"):
            print("[MJ] Wake listener stopped.")
            break

        text = listen_wake()

        if not text:
            continue

        if text.startswith("mj"):

            from main import run_mj

            command = text[2:].strip()

            if command:
                run_mj(command)
            else:
                speak("Ji Boss!")
