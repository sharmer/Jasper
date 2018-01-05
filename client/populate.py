# -*- coding: utf-8-*-
import os
import re
from getpass import getpass
import yaml
from pytz import timezone
import jasperpath


def run():
    profile = {}

    print("Welcome to the profile populator. \nIf, at any step, you'd prefer " +
          "not to enter the requested information, \njust hit 'Enter' with a " +
          "blank field to continue.")

    def simple_request(var, cleanVar, cleanInput=None):
        input = raw_input(cleanVar + ": ")
        if input:
            if cleanInput:
                input = cleanInput(input)
            profile[var] = input

    stt_engines = {
        "sphinx": "sphinx",
        "baidu":  "baidu-stt"
    }

    tips = "\nIf you would like to choose a specific STT " \
           "engine, please specify which.\nAvailable " \
           "implementations: %s. \n(Press Enter to  " \
           "default to PocketSphinx): " % (stt_engines.keys())
    stt_response = raw_input(tips)
    if (stt_response in stt_engines):
        profile["stt_engine"] = stt_engines[stt_response]

        tips = "\nWould you like to process the wake up word engine." \
               "\n(Press Enter to ignore): "
        stt_p_response = raw_input(tips)
        if (stt_p_response in stt_engines):
            profile["stt_passive_engine"] = stt_engines[stt_p_response]
    else:
        print("Unrecognized STT engine. Use defaut(PocketSphinx)")
        profile["stt_engine"] = "sphinx"

    tts_engines = {
        "espeak": "espeak-tts",
        "baidu":  "baidu-tts"
    }

    tips = "\nIf you would like to choose a specific TTS " \
           "engine, please specify which.\nAvailable " \
           "implementations: %s. \n(Press Enter to  " \
           "default to eSpeak): " % (tts_engines.keys())
    tts_response = raw_input(tips)
    if (tts_response in tts_engines):
        profile["tts_engine"] = tts_engines[tts_response]
    else:
        print("Unrecognized TTS engine. Use defaut(eSpeak)")
        profile["tts_engine"] = "espeak-tts"


    if stt_response == "baidu" or tts_response == "baidu":
        app_key = raw_input("\nChoosing Baidu request API Key and Secret Key" +
                            "\nPlease enter your API key: ")
        app_secret = raw_input("Please enter your Secret Key: ")
        profile["baidu_api"] = {"app_key": app_key, "app_secret": app_secret}


    # write to profile
    print("\nWriting to profile to %s..." % (jasperpath.config("profile.yml")))
    if not os.path.exists(jasperpath.CONFIG_PATH):
        os.makedirs(jasperpath.CONFIG_PATH)
    outputFile = open(jasperpath.config("profile.yml"), "w")
    yaml.dump(profile, outputFile, default_flow_style=False)
    print("Done.")

if __name__ == "__main__":
    run()
