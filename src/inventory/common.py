from config import Config
import cv2
import numpy as np
import keyboard
import time
from utils.custom_mouse import mouse
from template_finder import TemplateFinder
from ui_manager import detect_screen_object, ScreenObjects, center_mouse
from utils.misc import wait, trim_black, color_filter
from inventory import personal
from ui import view
from screen import grab
from dataclasses import dataclass
from logger import Logger

@dataclass
class BoxInfo:
    img: np.ndarray = None
    pos: tuple = None
    column: int = None
    row: int = None
    need_id: bool = False
    sell: bool = False
    keep: bool = False

def get_slot_pos_and_img(img: np.ndarray, column: int, row: int) -> tuple[tuple[int, int],  np.ndarray]:
    """
    Get the pos and img of a specific slot position in Inventory. Inventory must be open in the image.
    :param config: The config which should be used
    :param img: Image from screen.grab() not cut
    :param column: Column in the Inventory
    :param row: Row in the Inventory
    :return: Returns position and image of the cut area as such: [[x, y], img]
    """
    top_left_slot = (Config().ui_pos["inventory_top_left_slot_x"], Config().ui_pos["inventory_top_left_slot_y"])
    slot_width = Config().ui_pos["slot_width"]
    slot_height= Config().ui_pos["slot_height"]
    slot = (top_left_slot[0] + slot_width * column, top_left_slot[1] + slot_height * row)
    # decrease size to make sure not to have any borders of the slot in the image
    offset_w = int(slot_width * 0.12)
    offset_h = int(slot_height * 0.12)
    min_x = slot[0] + offset_w
    max_x = slot[0] + slot_width - offset_w
    min_y = slot[1] + offset_h
    max_y = slot[1] + slot_height - offset_h
    slot_img = img[min_y:max_y, min_x:max_x]
    center_pos = (int(slot[0] + (slot_width // 2)), int(slot[1] + (slot_height // 2)))
    return center_pos, slot_img

def slot_has_item(slot_img: np.ndarray) -> bool:
    """
    Check if a specific slot in the inventory has an item or not based on color
    :param slot_img: Image of the slot
    :return: Bool if there is an item or not
    """
    slot_img = cv2.cvtColor(slot_img, cv2.COLOR_BGR2HSV)
    avg_brightness = np.average(slot_img[:, :, 2])
    return avg_brightness > 16.0

def close(img: np.ndarray = None) -> np.ndarray:
    img = grab() if img is None else img
    if detect_screen_object(ScreenObjects.RightPanel, img).valid:
        keyboard.send("esc")
        wait(0.1, 0.2)
        if detect_screen_object(ScreenObjects.RightPanel).valid:
            success = view.return_to_play()
            if not success:
                return None
    return img

def calc_item_roi(self, img_pre, img_post):
    try:
        diff = cv2.absdiff(img_pre, img_post)
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        diff_thresh = cv2.threshold(gray, 1, 255, cv2.THRESH_BINARY)[1]

        blue_mask, _ = color_filter(img_pre, Config().colors["blue_slot"])
        red_mask, _ = color_filter(img_pre, Config().colors["red_slot"])
        green_mask, _ = color_filter(img_post, Config().colors["green_slot"])

        blue_red_mask = np.bitwise_or(blue_mask, red_mask)
        final = np.bitwise_and.reduce([blue_red_mask, green_mask, diff_thresh])
        _, roi = trim_black(final)
        return roi
    except BaseException as err:
        Logger.error(f"_calc_item_roi: Unexpected {err=}, {type(err)=}")
        return None

def tome_state(img: np.ndarray = None, tome_type: str = "tp", roi: list = None):
    img = img if img is not None else grab()
    if (tome_found := TemplateFinder().search([f"{tome_type.upper()}_TOME", f"{tome_type.upper()}_TOME_RED"], img, roi = roi, threshold = 0.8, best_match = True, normalize_monitor  =True)).valid:
        if tome_found.name == f"{tome_type.upper()}_TOME":
            state = "ok"
        else:
            state = "empty"
        position = tome_found.center
    else:
        state = position = None
    return state, position

def id_item_with_tome(item_location: list, id_tome_location: list):
    mouse.move(id_tome_location[0], id_tome_location[1], randomize=4, delay_factor=[0.4, 0.8])
    wait(0.2, 0.4)
    mouse.click(button="right")
    wait(0.2, 0.4)
    mouse.move(item_location[0], item_location[1], randomize=4, delay_factor=[0.4, 0.8])
    wait(0.2, 0.4)
    mouse.click(button="left")
    wait(0.2, 0.4)

def transfer_items(items: list, action: str = "drop") -> list:
    #requires open inventory / stash / vendor
    img = grab()
    filtered = []
    left_panel_open = detect_screen_object(ScreenObjects.LeftPanel, img).valid
    if action == "drop":
        filtered = [ item for item in items if item.keep == False and item.sell == False ]
    elif action == "sell":
        filtered = [ item for item in items if item.keep == False and item.sell == True ]
        if not left_panel_open:
            Logger.error(f"transfer_items: Can't perform, vendor is not open")
    elif action == "stash":
        if detect_screen_object(ScreenObjects.GoldBtnStash, img).valid:
            filtered = [ item for item in items if item.keep == True ]
        else:
            Logger.error(f"transfer_items: Can't perform, stash is not open")
    else:
        Logger.error(f"transfer_items: incorrect action param={action}")
    if filtered:
        # if dropping, control+click to drop unless left panel is open, then drag to middle
        # if stashing, control+click to stash
        # if selling, control+click to sell
        # TODO: if purchasing, right-click to buy
        # TODO: if purchasing stack, shift+right-click to buy
        if (action == "drop" and not left_panel_open) or action in ["sell", "stash"]:
            keyboard.send('ctrl', do_release=False)
            wait(0.2, 0.4)
        for item in filtered:
            attempts = 0
            while True:
                mouse.move(*item.pos, randomize=4, delay_factor=[0.2, 0.4])
                wait(0.2, 0.4)
                if Config().general["info_screenshots"]:
                    cv2.imwrite("./info_screenshots/info" + action + "_item_" + time.strftime("%Y%m%d_%H%M%S") + ".png", grab())
                mouse.press(button="left")
                wait(0.2, 0.4)
                mouse.release(button="left")
                wait(0.2, 0.4)
                if action == "drop" and left_panel_open:
                    center_mouse()
                    wait(0.2, 0.3)
                    mouse.press(button="left")
                    wait(0.2, 0.3)
                    mouse.release(button="left")
                    wait(0.2, 0.3)
                # check if item is still there
                slot_img = get_slot_pos_and_img(grab(), item.column, item.row)[1]
                if slot_has_item(slot_img):
                    attempts += 1
                else:
                    # items.remove(item) # causes ValueError sometimes
                    for cnt, o_item in enumerate(items):
                        if o_item.pos == item.pos:
                            items.pop(cnt)
                            break
                    break
                if attempts > 1:
                    break
        if (action == "drop" and not left_panel_open) or action in ["sell", "stash"]:
            keyboard.send('ctrl', do_press=False)
        wait(0.1)
    return items
