import pyautogui

def capture_screen():
    screenshot = pyautogui.screenshot()
    screenshot.save("current_screen.png")
    return "current_screen.png"