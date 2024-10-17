# type: ignore

from wifi import radio
from ssl import create_default_context
from socketpool import SocketPool
from adafruit_requests import Session
from adafruit_connection_manager import connection_manager_close_all
from adafruit_datetime import datetime, timezone

import os
import time

import board
from gc import mem_free
from terminalio import FONT
from rgbmatrix import RGBMatrix
from framebufferio import FramebufferDisplay

from adafruit_display_shapes.rect import Rect
from adafruit_display_shapes.circle import Circle
from adafruit_display_text.label import Label

from displayio import Group, release_displays


# 1. USER PARAMETERS
VERBOSE = False # print data

SHOW_ALERT = True # show alert icon if active alert for route
SHOW_LIVE = True # flash live icon if data is live

ON_HOUR = 12 # turn on hour (UTC)
OFF_HOUR = 3 # turn off hour (UTC)
RESTART_HOUR = 4 # restart hour (UTC)

TEXT_LABEL_LATENCY = 0.06 # scroll speed for top text label (and refresh speed at the end of each scroll)
LIVE_ICON_LATENCY = 6 # flash speed for live icon


# 2. OTHER PARAMETERS
WIFI_SSID = os.getenv("CIRCUITPY_WIFI_SSID")
WIFI_PASSWORD = os.getenv("CIRCUITPY_WIFI_PASSWORD")

AIO_USERNAME = os.getenv("ADAFRUIT_AIO_USERNAME")
AIO_KEY = os.getenv("ADAFRUIT_AIO_KEY")
TIME_URL = f"https://io.adafruit.com/api/v2/{AIO_USERNAME}/integrations/time/strftime?x-aio-key={AIO_KEY}&fmt=%25Y%3A%25m%3A%25d%3A%25H%3A%25M%3A%25S"

STOP_ID = "Q04" # MTA ID for 86th Street Station
ROUTE_ID = "Q" # MTA ID for Q Train
MTA_STOP_URL = f"https://demo.transiter.dev/systems/us-ny-subway/stops/{STOP_ID}?skip_service_maps=true&skip_alerts=true&skip_transfers=true"
MTA_STOP_URL_DIRECTIONS = ['downtown and brooklyn', 'downtown', 'brooklyn']
MTA_ROUTE_URL = f"https://demo.transiter.dev/systems/us-ny-subway/routes/{ROUTE_ID}?skip_service_maps=true&skip_estimated_headways=true"

DISPLAY_WIDTH = 64 # pixels
DISPLAY_HEIGHT = 32 # pixels

BACKGROUND_COLOR = 0x000000 # black
BIT_DEPTH = 2 # color depth

ROUTE_ICON_FONT = FONT # default font
TEXT_LABEL_FONT = FONT # default font

ROUTE_ICON_COLOR = 0xFCB80A # yellow
TEXT_LABEL_COLOR = 0x919492 # gray-white
ALERT_ICON_COLOR = 0xB22222 # red
LIVE_ICON_COLOR = 0x919492 # gray-white

if RESTART_HOUR == 0:
    RESTART_HOUR_PREV = 23
else:
    RESTART_HOUR_PREV = RESTART_HOUR - 1


# 3. METHOD TO GET CURRENT UTC TIME DATA
def get_time(requests):
    try:
        with requests.get(TIME_URL) as response:
            time_response = response.text
                
        year, month, day, hour, minute, second = map(int, time_response.replace(':', ' ').split())

        current_time = int(datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc).timestamp())
        current_hour = hour

        return current_time, current_hour
    
    except Exception as e:
        print(f"TIME URL response parse error: {e}")
        return None, None


# 4. METHOD TO GET MTA TRAIN DATA
def get_train(requests, current_time):
    if not current_time:
        return None, None, None, None
    
    try:
        mta_response = requests.get(MTA_STOP_URL).json()

        trains = mta_response["stopTimes"]

        target_trains = []
        for train in trains:
            direction_name = train['headsign']
            
            if direction_name.lower() in MTA_STOP_URL_DIRECTIONS:
                train_symbol = train['trip']['route']['id']
                destination_name = train["destination"]["name"]
                departure_time = int(train["departure"]["time"])
                remaining_time = departure_time - current_time

                target_trains.append({
                    'direction_name': direction_name,
                    'train_symbol': train_symbol,
                    'destination_name': destination_name,
                    'departure_time': departure_time,
                    'remaining_time': remaining_time
                    })

            if len(target_trains) >= 3: # get next 3 trains
                break
                
        times = [max(0, int(train['remaining_time']/60)) for train in target_trains]
        symbol = target_trains[0]['train_symbol']
        destination = target_trains[0]['destination_name']

        mta_response = requests.get(MTA_ROUTE_URL).json()
        alert = len(mta_response["alerts"]) > 0
        
        return times, symbol, destination, alert
    
    except Exception as e:
        print(f"MTA URL response parse error: {e}")
        return None, None, None, None


# 5. METHOD TO SCROLL TEXT HORIZONTALLY
def scroll(label):
    group = label[0]
    group.x -= 1  # move label left

    if group.x < -1*6*len(label.text):  # if label has moved full length, refresh to initial position and return True
        group.x = 0
        return True
    
    return False


# 6. WIFI SETUP
radio.connect(os.getenv("CIRCUITPY_WIFI_SSID"), os.getenv("CIRCUITPY_WIFI_PASSWORD"))
print(f"\nconnected to {os.getenv('CIRCUITPY_WIFI_SSID')}\n")

pool = SocketPool(radio)
context = create_default_context()
requests = Session(pool, context)


# 7. DISPLAY SETUP
release_displays() # release any existing displays

master_group = Group()
blank_group = Group()

matrix = RGBMatrix(
    width=DISPLAY_WIDTH,
    height=DISPLAY_HEIGHT,
    bit_depth=BIT_DEPTH,
    rgb_pins=[
        board.MTX_R1,
        board.MTX_G1,
        board.MTX_B1,
        board.MTX_R2,
        board.MTX_G2,
        board.MTX_B2,
    ],
    addr_pins=[
        board.MTX_ADDRA,
        board.MTX_ADDRB,
        board.MTX_ADDRC,
        board.MTX_ADDRD
    ],
    clock_pin=board.MTX_CLK,
    latch_pin=board.MTX_LAT,
    output_enable_pin=board.MTX_OE,
    serpentine=False,
    doublebuffer=True
)

display = FramebufferDisplay(matrix, auto_refresh=True)

# blank rectangle
blank_rectangle = Rect(
    width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, x=0, y=0, fill=BACKGROUND_COLOR
)

# draw initialization for blank group
blank_group.append(blank_rectangle)

# placeholder text labels
text_label_top = Label(
    font=TEXT_LABEL_FONT, color=TEXT_LABEL_COLOR, text='', x=25, y=10, scale=1
)
text_label_bottom = Label(
    font=TEXT_LABEL_FONT, color=TEXT_LABEL_COLOR, text='', x=25, y=22, scale=1
)

# border rectangles
border_rectangle_left = Rect(
    width=25, height=DISPLAY_HEIGHT, x=0, y=0, fill=BACKGROUND_COLOR
)
right_border_width = DISPLAY_WIDTH-25-36
border_rectangle_right = Rect(
    width=right_border_width, height=DISPLAY_HEIGHT, x=DISPLAY_WIDTH-right_border_width, y=0, fill=BACKGROUND_COLOR
)

# circles for route, offset 1 pixel to the right and down
route_circle_1 = Circle(
    x0=12, y0=15, r=9, fill=ROUTE_ICON_COLOR
)
route_circle_2 = Circle(
    x0=12, y0=15+1, r=9, fill=ROUTE_ICON_COLOR
)
route_circle_3 = Circle(
    x0=12+1, y0=15, r=9, fill=ROUTE_ICON_COLOR
)
route_circle_4 = Circle(
    x0=12+1, y0=15+1, r=9, fill=ROUTE_ICON_COLOR
)

# symbol for route ("Q")
route_label_1 = Label(
    font=TEXT_LABEL_FONT, color=BACKGROUND_COLOR, text=ROUTE_ID, x=10, y=16, scale=1
)
route_label_2 = Label(
    font=TEXT_LABEL_FONT, color=BACKGROUND_COLOR, text=ROUTE_ID, x=10+1, y=16, scale=1
)

# alert true/false icons
alert_true_icon = Circle(
    x0=5, y0=8, r=2, fill=ALERT_ICON_COLOR
)

# live true/false icons
live_on_icon = Rect(
    width=2, height=2, x=3, y=24, fill=LIVE_ICON_COLOR
)
live_off_icon = Rect(
    width=2, height=2, x=3, y=24, fill=BACKGROUND_COLOR
)

# draw initialization for master group
master_group.append(text_label_top)
master_group.append(text_label_bottom)

master_group.append(border_rectangle_left)
master_group.append(border_rectangle_right)

master_group.append(route_circle_1)
master_group.append(route_circle_2)
master_group.append(route_circle_3)
master_group.append(route_circle_4)

master_group.append(route_label_1)
master_group.append(route_label_2)

if SHOW_LIVE:
    master_group.append(live_on_icon)
else:
    master_group.append(live_off_icon)

# set display root group to master group and refresh display to update
display.root_group = master_group
display.refresh()


# 8. MAIN LOOP TO SHOW TRAINS
setup = False
reset = True
previous_hour = RESTART_HOUR

while True:
    if reset:
        i = 0
        active = True
        live = True

        if VERBOSE:
            print(f"setup: {setup}")
            print(f"free memory: {mem_free()}")

        # get UTC time data
        current_time, current_hour = get_time(requests)

        if current_time and isinstance(current_hour, int):
            if (previous_hour == RESTART_HOUR_PREV and current_hour == RESTART_HOUR) or mem_free() < 1000: # restart at restart hour or low memory
                display.root_group = blank_group
                display.refresh()
                break
            
            if ON_HOUR < OFF_HOUR:
                if current_hour < ON_HOUR or OFF_HOUR <= current_hour: # turn off at night
                    active = False
            else:
                if ON_HOUR > current_hour and current_hour >= OFF_HOUR: # turn off at night
                    active = False
            
            if VERBOSE:
                print(f"active: {active}\n")

            if not active:
                display.root_group = blank_group
                display.refresh()
                time.sleep(10)
                continue

            previous_hour = current_hour

            if VERBOSE:
                print(f"current_time: {current_time}")
                print(f"current_hour: {current_hour}")
            
        else:
            live = False

        # get MTA train data
        times, symbol, destination, alert = get_train(requests, current_time)

        if times and symbol and destination and alert in [True, False]:
            
            formatted_times = ','.join([str(t) for t in times[:3]])
            if len(formatted_times) > 6:
                formatted_times = ','.join([str(t) for t in times[:2]])
            
            formatted_symbol = str(symbol)

            formatted_destination = str(destination)

            formatted_alert = bool(alert)

            if VERBOSE:
                print(f"times: {formatted_times}")
                print(f"symbol: {formatted_symbol}")
                print(f"destination: {formatted_destination}")
                print(f"alert: {formatted_alert}")
            
        else:
            live = False
        
        if VERBOSE:
            print(f"live: {live}\n")

        if live:
            # mark setup as complete
            setup = True
            
            # draw text 
            text_label_top = Label(
                font=TEXT_LABEL_FONT, color=TEXT_LABEL_COLOR, text=formatted_destination, x=25, y=10, scale=1
            )
            text_label_bottom = Label(
                font=TEXT_LABEL_FONT, color=TEXT_LABEL_COLOR, text=formatted_times, x=25, y=22, scale=1
            )
            
            # update text labels on master group
            master_group.pop(0)
            master_group.insert(0, text_label_top)

            master_group.pop(1)
            master_group.insert(1, text_label_bottom)

            # update alert icon on master group
            if SHOW_ALERT:
                if alert:
                    if len(master_group) >= 12:
                        master_group.pop(11)
                    master_group.insert(11, alert_true_icon)
                else:
                    if len(master_group) >= 12:
                        master_group.pop(11)
            
        else:
            if SHOW_LIVE:
                # update live icon on master group
                master_group.pop(10)
                master_group.insert(10, live_on_icon)
        
        # set display root group to master group
        display.root_group = master_group

    # if setup completed
    if setup:
        # scroll text and update reset condition
        reset = scroll(text_label_top)

        # flash live icon if data is live
        if SHOW_LIVE:
            if live:
                if i % (LIVE_ICON_LATENCY*2) == 0:
                    master_group.pop(10)
                    master_group.insert(10, live_off_icon)
                elif i % LIVE_ICON_LATENCY == 0:
                    master_group.pop(10)
                    master_group.insert(10, live_on_icon)

        # refresh display to update
        if not reset:
            display.refresh(minimum_frames_per_second=0)
        
        i += 1

        # wait before next iteration
        time.sleep(TEXT_LABEL_LATENCY)

    # if setup failed
    else:
        reset = True
        
        # wait before retrying
        time.sleep(5)
    

# 9. CLEANUP
display.root_group = blank_group
connection_manager_close_all(pool)

if VERBOSE:
    print("\nrestarting")
