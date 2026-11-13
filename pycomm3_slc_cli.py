
'''
The pycomm3_slc_cli application is intended to encaspulate all of the pycomm3 
commands into a single directly executable program.  Using pyinstaller,
pycomm3_slc_cli can be packaged into an .exe file that can be run on any Windows
computer without the need for installing Python.  This can be particularly
handy for systems where an end-user does not have the Rockwell software, but
needs to update a value, set the time on the controller or read or write
settings from or to the target PLC.

Execution of the application will take the form of a single command or a shell
console application allowing multiple commands to be executed.

Single command syntax:
pycomm3_slc_cli 192.168.1.10 Read N9:0
n9:0, 21809, N, None

Console app example:
pycomm3_slc_cli 192.168.1.10
> Read N9:0
n9:0, 21809, N, None
> quit

- or -

pycomm3_slc_cli
> Read CurrentScreen
ERROR - No IPAdress specified.  Use IPAddress command.
> IPAddress 192.168.1.10
> Read N9:0
n9:0, 21809, N, None
> quit

'''

import sys
import datetime
import time
import textwrap

from pycomm3 import SLCDriver
from pathlib import Path
version = "0.3.1"
comm = None
output_format = "raw"
output_formats = ["raw", "readable", "minimal"]
show_timing = False

# CONSTANTS
NOTFOUND = -1


#region HELPER FUNCTIONS
def isNumber(s):
    try:
        float(s)
        return True
    except ValueError:
        return False

def getErrorMessage(error):
    # pycomm3 wraps the real failure in exceptions of its own, so the outermost
    # message ("failed to open a connection") is the least informative one.
    # Walk down to the root cause, which is where the actual reason lives.
    root = error
    visited = []
    while (root != None and not id(root) in visited):
        visited.append(id(root))
        cause = root.__cause__ if root.__cause__ != None else root.__context__
        if (cause == None):
            break
        root = cause
    message = str(root).strip()
    if (len(message) == 0):
        return type(root).__name__
    return message

def getNumber(s):
    assert isNumber(s), "Expected a number, got {0}".format(s)
    if isinstance(s, str):
        if s.isnumeric():
            return int(s)
        else: 
            return float(s)
    else:
        return s
        
#endregion HELPER FUNCTIONS

#region DATA HELPER FUNCTIONS
def getTagValues(tags):
    outData = []
    for tag in tags:
        if len(tag) > 0:
            try:
                result = comm.read(tag)
            except Exception as error:
                #print("Error reading: " + tag + " - " + str(error))
                outData += [tag + "=!ERROR!"]
                continue
            outData += [tag + "=" + str(result.value)]
    return outData

def convertToWordBit(tag):
    if ((not ":" in tag) and ("/" in tag)):
        file = tag.split("/")[0]
        bitPos = int(tag.split("/")[1])
        word = int(bitPos/16)
        bit = bitPos % 16
        converted_tag = file + ":" + str(word) + "/" + str(bit)
    else:
        converted_tag = tag
    return converted_tag

def foundFile(file, files):
    result = [i for i in range(len(files)) if files[i]["file"] == file]
    if (len(result) > 0):
        return result[0]
    else:
        return -1

def getOptimizedTag(file, maxElements):
    length = file["end_word"] - file["start_word"] + 1
    outData = []
    start_word = file["start_word"]
    loop = length / maxElements
    while loop > 1:
        outData.append(file["file"] + ":" + str(start_word) \
            + "{" + str(maxElements) + "}")
        start_word += maxElements
        loop -= 1
    outData.append(file["file"] + ":" + str(start_word) \
        + "{" + str(file["end_word"] - start_word + 1) + "}")
    return outData

def getTagValuesFromFile(filename):
    tags = []
    try:
        tags = Path(filename).read_text().split("\n")
    except Exception as error:
        print("ERROR - Error opening the file {0}. {1}".format(filename, str(error)))
        return []
    outData = getTagValues(tags)
    return outData

def getTagParts(tag):
    tag = convertToWordBit(tag)
    file = tag.split(":")[0]
    word = NOTFOUND
    bit = NOTFOUND
    if "/" in tag:
        word = int(tag.split(":")[1].split("/")[0])
        bit = int(tag.split("/")[1])
    elif tag.split(":")[1].isnumeric():
        word = int(tag.split(":")[1])
    return {"file": file, "word": word, "bit": bit}

def getDataParts(data):
    file = data.split(":")[0]
    wordString = data.split(":")[1].split("{")[0]
    word = NOTFOUND
    if wordString.isnumeric():
        word = int(wordString)
    dataString = data.split("=")[1]
    dataArray = []
    if "[" in dataString:
        dataStringArray = dataString.split("[")[1].split("]")[0].split(",")
        if file.startswith("F"):
            dataArray = [float(i) for i in dataStringArray]
        else:
            dataArray = [int(i) for i in dataStringArray]
    elif not isNumber(dataString):
        dataArray = [dataString]
    else:
        dataArray = [int(dataString)]
    length = len(dataArray)
    end_word = word + length - 1
    return {"file": file, "start_word": word, "length": length, 
            "end_word": end_word ,"data": dataArray}

def getTagValueFromData(tag, tagData):
    tagParts = getTagParts(tag)
    for data in tagData:
        dataParts = getDataParts(data)
        if tagParts["file"] == dataParts["file"]:
            if tagParts["word"] >= dataParts["start_word"] and tagParts["word"] <= dataParts["end_word"]:
                wordPos = tagParts["word"] - dataParts["start_word"]
                if dataParts["data"][0] == "!ERROR!":
                    return "!ERROR!"
                wordData = getNumber(dataParts["data"][wordPos])
                if "/" in tag and tagParts["bit"] != NOTFOUND:
                    return (wordData & 2**tagParts["bit"]) == 2**tagParts["bit"]
                else:
                    return wordData                    
    return "NONE"

#endregion DATA HELPER FUNCTIONS


#region FAULT CODE DEFINITIONS
'''
Major error fault codes for the SLC 500 family of processors.

Source: Allen-Bradley SLC 500 Instruction Set Reference Manual, publication
1747-RM001G-EN-P (November 2008) - Chapter 16 "Troubleshooting Faults"
(Tables 16.1 through 16.6) and Appendix B "SLC Status File" (Table B.2 for
S:5, S:6 and S:54, Table B.3 for the S:6 error code classifications).

S:6  holds the major error fault code for the current or most recent major
     error.  The processor never clears this word, so a non-zero value does
     not by itself mean the processor is faulted right now - the major error
     halted bit S:1/13 tells you that.
S:54 mirrors the last error code value stored in S:6.  It exists on the
     SLC 5/03, 5/04 and 5/05 processors only.

Rockwell documents the codes in hexadecimal.  Codes written as xxNN carry
additional information in the high byte: the slot number for the I/O errors,
or the data file number for code xx39.
'''

# Fault classifications (Table B.3).
FAULT_NONUSER = "Non-User fault - the user fault routine does not execute."
FAULT_NONRECOVERABLE = "Non-Recoverable user fault - the user fault routine " \
    "executes for one pass."
FAULT_RECOVERABLE = "Recoverable user fault - the user fault routine may " \
    "clear the fault by clearing S:1/13."
FAULT_UNCLASSIFIED = "Classification not listed in the Rockwell documentation."

# Causes and actions repeated across many of the codes.
NOISE_CAUSE = "noise, lightning, improper grounding, lack of surge suppression " \
    "on outputs with inductive loads, or a poor power source"
RELOAD_ACTION = "Correct the problem ({0}), reload the program and run.  The " \
    "autoload feature with a memory module can reload the program and enter " \
    "the Run mode automatically.".format(NOISE_CAUSE)
RELOAD_SW_ACTION = "Correct the problem ({0}), reload the program and run.  If " \
    "the error persists, use current programming software to develop and load " \
    "the program.".format(NOISE_CAUSE)
MEMORY_MODULE_ACTION = "The memory module is corrupted.  Re-program the memory " \
    "module.  If the error persists, replace the memory module."
SPECIALTY_ACTION = "Refer to the user manual supplied with the specialty I/O " \
    "module."
JSR_ACTION = "Correct the user program to meet the requirements and " \
    "restrictions for the JSR instruction, then reload the program and run."
FILE_SPACE_ACTION = "Correct the user program or allocate more data file space " \
    "using the memory map, then reload and run."

# Fully specified fault codes.
# {code: (description, classification, recommended action)}
FAULT_CODES = {
    0x0001: ("NVRAM error.", FAULT_NONUSER, RELOAD_ACTION),
    0x0002: ("Unexpected hardware watchdog timeout.", FAULT_NONUSER,
             RELOAD_ACTION),
    0x0003: ("Memory module memory error.  This error can also occur when "
             "going to the REM Run mode.", FAULT_NONUSER,
             MEMORY_MODULE_ACTION),
    0x0004: ("Memory error occurred while in the Run mode.", FAULT_NONUSER,
             RELOAD_ACTION),
    0x0005: ("Reserved.", FAULT_RECOVERABLE,
             "This code is reserved by Rockwell Automation and is not "
             "documented.  Contact Rockwell Automation technical support."),
    0x0006: ("Reserved.", FAULT_RECOVERABLE,
             "This code is reserved by Rockwell Automation and is not "
             "documented.  Contact Rockwell Automation technical support."),
    0x0007: ("Failure during memory module transfer.", FAULT_NONUSER,
             MEMORY_MODULE_ACTION),
    0x0008: ("Internal software error.", FAULT_NONUSER,
             RELOAD_ACTION + "  If the problem re-occurs, contact your local "
             "Rockwell Automation representative."),
    0x0009: ("Internal hardware error.", FAULT_NONUSER,
             RELOAD_ACTION + "  If the problem re-occurs, contact your local "
             "Rockwell Automation representative."),
    0x0010: ("The processor does not meet the required revision level.",
             FAULT_NONUSER,
             "The revision level of the processor is not compatible with the "
             "revision level the program was developed for.  Consult your local "
             "Rockwell Automation representative to purchase an upgrade kit for "
             "the processor."),
    0x0011: ("The executable program file number 2 is absent.", FAULT_NONUSER,
             "An incompatible or corrupt program is present.  Reload the "
             "program or re-create it with the programming software."),
    0x0012: ("The ladder program has a memory error.", FAULT_NONUSER,
             RELOAD_SW_ACTION),
    0x0013: ("The required memory module is absent, or S:1/10 or S:1/11 is not "
             "set as required by the program.", FAULT_RECOVERABLE,
             "Either install a memory module in the processor, or upload the "
             "program from the processor to the memory module."),
    0x0014: ("Internal file error.", FAULT_NONUSER, RELOAD_SW_ACTION),
    0x0015: ("Configuration file error.", FAULT_NONUSER, RELOAD_SW_ACTION),
    0x0016: ("Startup protection after power loss.  The error condition exists "
             "at powerup when bit S:1/9 is set and powerdown occurred while "
             "running.", FAULT_RECOVERABLE,
             "Either reset bit S:1/9 if that is consistent with the application "
             "requirements and change the mode back to Run, or clear S:1/13, "
             "the major fault bit, before the end of the first program scan is "
             "reached."),
    0x0017: ("NVRAM / memory module user program mismatch.",
             FAULT_NONRECOVERABLE,
             "Bit S:2/9 is set and the memory module user program does not "
             "match the NVRAM user program.  Transfer the memory module program "
             "to NVRAM, then change to the Run mode."),
    0x0018: ("Incompatible user program - operating system type mismatch.  This "
             "error can also occur during powerup.", FAULT_NONUSER,
             "The user program is too advanced to be executed by the current "
             "operating system.  Contact your local Rockwell Automation "
             "representative to purchase an upgrade kit for the processor."),
    0x0019: ("A missing or duplicate label number was detected.",
             FAULT_NONRECOVERABLE,
             "A duplicate or missing label instruction was found in a "
             "subroutine.  Either remove the duplicate label or add the missing "
             "label."),
    0x001F: ("A program integrity problem occurred during an online editing "
             "session.", FAULT_NONUSER,
             "Noise, communication loss or a power cycle occurred during an "
             "online edit session.  Reload the program and re-enter your "
             "changes."),
    0x0020: ("A minor error bit is set at the end of the scan.  Refer to the "
             "S:5 minor error bits (lower byte only).", FAULT_RECOVERABLE,
             "Either a math or FRD instruction overflow occurred, a sequencer or "
             "shift register instruction error was detected, a major error was "
             "detected while executing a user fault routine, or M0-M1 file "
             "addresses were referenced in the user program for a disabled "
             "slot.  Correct the programming problem, clear minor error bits "
             "S:5/0-7 along with S:1/13, reload the program and enter the Run "
             "mode."),
    0x0021: ("A remote power failure of an expansion I/O chassis has occurred.",
             FAULT_NONUSER,
             "Re-apply power to the expansion chassis (on fixed and FRN 1 to 4 "
             "SLC 5/01 processors, cycle power on the local chassis).  Note that "
             "a modular system that encounters an over-voltage or over-current "
             "condition in any of its power supplies can produce any of the I/O "
             "error codes instead of this one; that condition is indicated by "
             "the power supply LED being off."),
    0x0022: ("The user watchdog scan time has been exceeded.",
             FAULT_NONRECOVERABLE,
             "Either the watchdog time is set too low for the user program or "
             "the user program is caught in a loop.  Either increase the "
             "watchdog timeout in the status file (S:3H) or correct the user "
             "program problem."),
    0x0023: ("Invalid or non-existent STI interrupt file.",
             FAULT_NONRECOVERABLE,
             "Either disable the STI interrupt setpoint (S:30) and file number "
             "(S:31) in the status file, or create the STI interrupt subroutine "
             "file for the file number assigned in S:31.  The file number must "
             "not be 0, 1 or 2."),
    0x0024: ("Invalid STI interrupt interval (greater than 2550 ms or "
             "negative).", FAULT_NONRECOVERABLE,
             "The STI setpoint is out of range.  Either disable the STI "
             "interrupt setpoint (S:30) and file number (S:31) in the status "
             "file, or correct the setpoint."),
    0x0025: ("Excessive stack depth / JSR calls for the STI routine.",
             FAULT_NONRECOVERABLE,
             "A JSR instruction is calling a file number assigned to an STI "
             "routine.  " + JSR_ACTION),
    0x0026: ("Excessive stack depth / JSR calls for an I/O interrupt routine.",
             FAULT_NONRECOVERABLE,
             "A JSR instruction is calling a file number assigned to an I/O "
             "interrupt routine.  " + JSR_ACTION),
    0x0027: ("Excessive stack depth / JSR calls for the user fault routine.",
             FAULT_NONRECOVERABLE,
             "A JSR instruction is calling a file number assigned to the user "
             "fault routine.  " + JSR_ACTION),
    0x0028: ("Invalid or non-existent \"startup protection\" fault routine file "
             "value.", FAULT_NONUSER,
             "Either a fault routine file number was created in the status file "
             "but the fault routine file was not physically created, or the file "
             "number created was 0, 1 or 2.  Either disable the fault routine "
             "file number (S:29) in the status file, or create a fault routine "
             "for the file number referenced in S:29."),
    0x0029: ("Indexed address reference is outside of the entire data file space "
             "(range of B3:0 through the last file).", FAULT_RECOVERABLE,
             "The program is referencing, through indexed addressing, an element "
             "beyond the allowed range.  Correct and reload the user program.  "
             "This problem cannot be corrected by writing to the index register "
             "word (S:24).  Note the processor uses an index value of zero for "
             "the faulted instruction following error recovery."),
    0x002A: ("Indexed address reference is beyond the specific referenced data "
             "file.", FAULT_NONRECOVERABLE,
             "The program is referencing, through indexed addressing, an element "
             "beyond a file boundary.  Correct the user program, allocate more "
             "data space using the memory map, or re-save the program allowing "
             "crossing of file boundaries.  This problem cannot be corrected by "
             "writing to the index register word (S:24)."),
    0x002B: ("An invalid file number for an indirect address exists.",
             FAULT_RECOVERABLE,
             "Either the file number exists but is not the correct file type, or "
             "the file number does not exist.  Check the file type or create the "
             "file number."),
    0x002C: ("The referenced indirect address element is outside data file "
             "limits.", FAULT_RECOVERABLE,
             "The indirectly referenced element does not exist, but the file "
             "type is correct and it exists.  Create the indirectly referenced "
             "element."),
    0x002D: ("An invalid referenced indirect address subelement exists.",
             FAULT_RECOVERABLE,
             "Either a subelement is referenced incorrectly or an indirect "
             "reference has been made to an M file.  Correct the references and "
             "try again."),
    0x002E: ("Invalid DII input slot.", FAULT_RECOVERABLE,
             "The referenced slot is empty or a non-discrete I/O card is "
             "present.  Change the input slot to a discrete I/O card."),
    0x002F: ("Invalid or non-existent DII interrupt file.",
             FAULT_NONRECOVERABLE,
             "Either a DII interrupt file number was assigned in the status file "
             "but the subroutine file was not created, or the DII interrupt file "
             "number assigned was 0, 1 or 2.  Either disable the DII function by "
             "writing a zero to this location, or change the value to a valid "
             "ladder file (3-255)."),
    0x0030: ("An attempt was made to jump to one too many nested subroutine "
             "files.  This code can also mean that a program has potentially "
             "recursive routines.", FAULT_NONRECOVERABLE,
             "Either more than the maximum of 4 levels of nested subroutines (8 "
             "on a 5/02 or 5/03 processor) are called for in the user program, or "
             "nested subroutines are calling subroutines of a previous level.  "
             + JSR_ACTION),
    0x0031: ("An unsupported instruction reference was detected.",
             FAULT_NONRECOVERABLE,
             "The type or series level of the processor does not support an "
             "instruction residing in the user program, or a constant has been "
             "programmed as the first operand of a compare instruction.  Either "
             "replace the processor with one that supports the user program, or "
             "modify the user program so that all instructions are supported by "
             "the processor, then reload the program and run."),
    0x0032: ("A sequencer instruction length / position parameter points past "
             "the end of a data file.", FAULT_RECOVERABLE, FILE_SPACE_ACTION),
    0x0033: ("The length parameter of an LFU, LFL, FFU, FFL, BSL or BSR "
             "instruction points past the end of a data file.",
             FAULT_RECOVERABLE, FILE_SPACE_ACTION),
    0x0034: ("A negative value for a timer accumulator or preset value was "
             "detected.  On fixed processors with 24V DC inputs only: a negative "
             "or zero HSC preset was detected in an HSC instruction (the valid "
             "range is 1 to 32767).", FAULT_RECOVERABLE,
             "If the user program is moving values to the accumulated or preset "
             "word of a timer, make certain these values cannot be negative.  "
             "Correct the user program, reload and run."),
    0x0035: ("A TND, SVC or REF instruction is called within an interrupting or "
             "user fault routine.", FAULT_NONRECOVERABLE,
             "Using a TND, SVC or REF instruction in an interrupt or user fault "
             "routine is illegal.  Correct the user program, reload and run."),
    0x0036: ("An invalid value is being used for a PID instruction parameter.",
             FAULT_RECOVERABLE,
             "An invalid value was loaded into a PID instruction by the user "
             "program or by the user via the data monitor function.  See the PID "
             "runtime errors in the SLC 500 Instruction Set Reference Manual."),
    0x0038: ("A RET instruction was detected in a non-subroutine file.",
             FAULT_NONUSER,
             "A RET instruction resides in the main program.  Correct the user "
             "program, reload and run."),
    0x003A: ("An attempt to write to a protected data file occurred.",
             FAULT_UNCLASSIFIED,
             "An attempt was made to write to an indirect address located in a "
             "file that has constant data file protection.  Remove the "
             "protection and retry the function."),
    0x003B: ("Motherboard and daughter card firmware do not match.",
             FAULT_UNCLASSIFIED,
             "The motherboard and daughter card were not flash upgraded as a "
             "pair.  Flash upgrade both the motherboard and the daughter card to "
             "the latest version."),
    0x003C: ("STI watchdog timer time-out.", FAULT_UNCLASSIFIED,
             "The STI setpoint is set too low - the processor was not able to "
             "service the STI interrupt before its watchdog timer timed out.  "
             "Increase the value of the STI setpoint (S:30)."),
    0x003D: ("J4 jumper in wrong position.", FAULT_UNCLASSIFIED,
             "Move the J4 jumper on the processor to the correct position."),
    0x0056: ("The chassis configuration specified in the user program is "
             "detected as being incorrect.", FAULT_NONUSER,
             "The chassis configuration specified by the user does not match the "
             "hardware.  Correct the chassis configuration, reload the program "
             "and run."),
    0x005F: ("Invalid rack ID (handshake error).", FAULT_NONUSER,
             "Invalid rack setup or a problem with the rack.  For a multi-rack "
             "system, make sure no more than three racks are configured.  For a "
             "single-rack system the rack may be bad - replace the rack."),
    0x00A0: ("A communications channel hardware fault has occurred on channel 0 "
             "(a major fault unique to the SLC 5/04 and SLC 5/05).",
             FAULT_NONUSER,
             "Ethernet, DH+ and RS-232 communications will be disabled until a "
             "power cycle is performed.  The fault may be cleared via a write to "
             "the system status file, but communications stay disabled until "
             "power is cycled."),
    0x00A1: ("A communications channel hardware fault has occurred on channel 1 "
             "- the Ethernet channel on an SLC 5/05, or the DH+ channel on an "
             "SLC 5/04.", FAULT_NONUSER,
             "Ethernet, DH+ and RS-232 communications will be disabled until a "
             "power cycle is performed.  On an SLC 5/05, word 15 of the system "
             "status file (S:15) provides a specific fault code for the Ethernet "
             "daughterboard."),
    0x00A2: ("A communications channel hardware fault has occurred (a major "
             "fault unique to the SLC 5/04 and SLC 5/05).", FAULT_NONUSER,
             "Ethernet, DH+ and RS-232 communications will be disabled until a "
             "power cycle is performed.  The fault may be cleared via a write to "
             "the system status file, but communications stay disabled until "
             "power is cycled."),
}

# Codes documented as xxNN, where the high byte carries additional information.
# {low byte: (description, classification, recommended action)}
SLOT_FAULT_CODES = {
    0x39: ("An invalid string length was detected in a string file.",
           FAULT_RECOVERABLE,
           "The first word of the string data contains a negative value, zero, "
           "or a value greater than 82.  Check the first word of the string data "
           "elements for invalid values and correct the user data."),
    0x50: ("A chassis data error is detected.", FAULT_RECOVERABLE,
           "Correct the problem ({0}), clear the fault and re-enter the Run "
           "mode.".format(NOISE_CAUSE)),
    0x51: ("A \"stuck\" runtime error is detected on an I/O module.",
           FAULT_NONRECOVERABLE,
           "If this is a discrete I/O module this is a noise problem - cycle "
           "power to the system, and if that does not correct the problem "
           "replace the module.  If this is a specialty I/O module, refer to its "
           "user manual for the probable cause."),
    0x52: ("A module required for the user program is detected as missing or "
           "removed.", FAULT_RECOVERABLE,
           "Either disable the slot in the status file (S:11 and S:12), or "
           "insert the required module in the slot."),
    0x53: ("When going to Run, the user program declares the slot as unused and "
           "that slot is detected as having an I/O module inserted.  This code "
           "can also mean that an I/O module has reset itself.  On an SLC 5/03 "
           "and higher it can also mean an attempt was made to enter the Run or "
           "Test mode with an empty chassis.", FAULT_RECOVERABLE,
           "Either disable the slot in the status file (S:11 and S:12) and clear "
           "the fault, remove the module and clear the fault, or modify the I/O "
           "configuration to include the module and reload the program.  If you "
           "suspect the module has reset itself, clear the major fault and run.  "
           "For an empty chassis, disable all slots in that chassis."),
    0x54: ("A module required for the user program is detected as being the "
           "wrong type.", FAULT_RECOVERABLE,
           "The module in the slot is a different type than was configured for "
           "that slot.  Either replace the module with the correct module and "
           "clear the fault, or change the I/O configuration for the slot and "
           "reload the program."),
    0x55: ("A discrete I/O module required for the user program is detected as "
           "having the wrong I/O count.  This code can also mean that a "
           "specialty card driver is incorrect.", FAULT_RECOVERABLE,
           "For a discrete I/O module, either replace it with a module having "
           "the I/O count selected in the I/O configuration, or change the I/O "
           "configuration to match the existing module and reload the program.  "
           "For a specialty I/O module, " + SPECIALTY_ACTION),
    0x56: ("The chassis configuration specified in the user program is detected "
           "as being incorrect.", FAULT_NONUSER,
           "The chassis configuration specified by the user does not match the "
           "hardware.  Correct the chassis configuration, reload the program and "
           "run."),
    0x57: ("A specialty I/O module has not responded to a Lock Shared Memory "
           "command within the required time limit.", FAULT_RECOVERABLE,
           "Cycle chassis power.  If this does not correct the problem, " +
           SPECIALTY_ACTION + "  You may have to replace the module."),
    0x58: ("A specialty I/O module has generated a generic fault.  The card "
           "fault bit is set in the module's status byte.",
           FAULT_NONRECOVERABLE,
           "Cycle chassis power.  If this does not correct the problem, " +
           SPECIALTY_ACTION + "  You may have to replace the module."),
    0x59: ("A specialty I/O module has not responded to a command as being "
           "completed within the required time limit.", FAULT_RECOVERABLE,
           SPECIALTY_ACTION + "  You may have to replace the module."),
    0x5A: ("Hardware interrupt problem.", FAULT_NONRECOVERABLE,
           "Cycle chassis power.  Check for a noise problem and be sure proper "
           "grounding practices are used.  If this is a specialty I/O module, " +
           SPECIALTY_ACTION + "  You may have to replace the module."),
    0x5B: ("G file configuration error - the user program G file size exceeds "
           "the capacity of the module.", FAULT_RECOVERABLE,
           SPECIALTY_ACTION + "  Reconfigure the G file as directed in the "
           "manual, then reload and run."),
    0x5C: ("M0-M1 file configuration error - the user program M0-M1 file size "
           "exceeds the capacity of the module.", FAULT_RECOVERABLE,
           SPECIALTY_ACTION + "  Reconfigure the M0-M1 files as directed in the "
           "manual, then reload and run."),
    0x5D: ("The interrupt service requested is not supported by the processor.",
           FAULT_RECOVERABLE,
           SPECIALTY_ACTION + "  Determine which processors support use of the "
           "module and change to a processor that supports it."),
    0x5E: ("Processor I/O driver (software) error.", FAULT_RECOVERABLE,
           "The processor I/O driver software is corrupt.  Reload the program "
           "using the programming software."),
    0x90: ("Interrupt problem on a disabled slot.", FAULT_NONRECOVERABLE,
           "A specialty I/O module requested service while the slot was "
           "disabled.  " + SPECIALTY_ACTION + "  You may have to replace the "
           "module."),
    0x91: ("A disabled slot has faulted.", FAULT_NONRECOVERABLE,
           "Cycle chassis power.  If this does not correct the problem, " +
           SPECIALTY_ACTION + "  You may have to replace the module."),
    0x92: ("Invalid or non-existent module interrupt subroutine (ISR) file.",
           FAULT_NONRECOVERABLE,
           "The I/O configuration / ISR file information for the specialty I/O "
           "module is incorrect.  " + SPECIALTY_ACTION + "  Correct the "
           "information, then reload the program and run."),
    0x93: ("Unsupported I/O module specific major error.",
           FAULT_NONRECOVERABLE,
           "The processor does not recognize the error code reported by the "
           "specialty I/O module.  " + SPECIALTY_ACTION),
    0x94: ("A module has been detected as being inserted under power in the Run "
           "or Test mode.  This can also mean that an I/O module has reset "
           "itself.", FAULT_NONRECOVERABLE,
           "No module should ever be inserted in a chassis under power.  If the "
           "module is not damaged, either remove the module, clear the fault and "
           "run, or add the module to the I/O configuration, reference it in the "
           "user program where required, reload the program and run."),
}

# Codes documented as a range of xxNN values.
# (first low byte, last low byte, description, classification, action)
SLOT_FAULT_RANGES = [
    (0x60, 0x6F, "Identifies an I/O module specific recoverable major error.",
     FAULT_RECOVERABLE, SPECIALTY_ACTION),
    (0x70, 0x7F,
     "Identifies an I/O module specific non-recoverable major error.",
     FAULT_NONRECOVERABLE, SPECIALTY_ACTION),
    (0x80, 0x8F,
     "Identifies a specialty I/O module specific non-recoverable major error.",
     FAULT_NONUSER, SPECIALTY_ACTION),
]

# The minor error bits of S:5 that revert to major error 0020 at the end of the
# scan (Table B.2).  Bits 1 and 5 through 7 are reserved.
MINOR_ERROR_BITS = {
    0: "S:5/0 Overflow trap - a mathematical overflow occurred in the ladder "
       "program (ADD, SUB, MUL, DIV, DDV, NEG, SCL, TOD or FRD).",
    2: "S:5/2 Control register error - the error bit of an LFU, LFL, FFU, FFL, "
       "BSL, BSR, SQO, SQC or SQL instruction has been set.",
    3: "S:5/3 A major error was detected while executing the user fault routine "
       "due to another major error.",
    4: "S:5/4 An M0 or M1 module file element was referenced for a slot that is "
       "disabled via its I/O slot enable bit.",
}

#endregion FAULT CODE DEFINITIONS

#region FAULT CODE HELPER FUNCTIONS
def getSlotDescription(slot):
    # Table 16.5 / Table B.3 - the high byte of an I/O fault code is the slot
    # number in hexadecimal.  1F means the slot could not be determined on a
    # modular controller; 03 means the same on a fixed 500 controller.
    if slot == 0x1F:
        return "The high byte 0x1F means the exact slot could not be " \
               "determined (modular controller)."
    if slot == 0x03:
        return "The high byte 0x03 identifies slot 3.  On a fixed 500 " \
               "controller this value instead means the exact slot could not " \
               "be determined."
    if slot <= 0x1E:
        return "The high byte 0x{0:02X} identifies slot {0}.".format(slot)
    return "The high byte 0x{0:02X} is outside the documented slot range of " \
           "0x00 to 0x1F.".format(slot)

def describeFaultCode(code):
    # Returns a dictionary describing a major error fault code read from S:6 or
    # S:54.  "detail" holds the interpretation of any information carried in the
    # high byte of the code, such as the slot number.
    code = int(code) & 0xFFFF
    result = {"value": code, "code": "{0:04X}".format(code), "detail": []}
    if code == 0:
        result["description"] = "No major error fault code is recorded."
        result["classification"] = ""
        result["action"] = ""
        return result
    if code in FAULT_CODES:
        description, classification, action = FAULT_CODES[code]
        result["description"] = description
        result["classification"] = classification
        result["action"] = action
        return result
    low = code & 0x00FF
    high = (code & 0xFF00) >> 8
    entry = SLOT_FAULT_CODES.get(low)
    if entry == None:
        for first, last, description, classification, action in SLOT_FAULT_RANGES:
            if first <= low <= last:
                entry = (description, classification, action)
                break
    if entry != None:
        description, classification, action = entry
        result["description"] = description
        result["classification"] = classification
        result["action"] = action
        if low == 0x39:
            result["detail"].append("The high byte 0x{0:02X} identifies data "
                                    "file number {0}.".format(high))
        else:
            result["detail"].append(getSlotDescription(high))
        return result
    result["description"] = "This code is not listed in the Rockwell SLC 500 " \
        "documentation.  It may be an application specific major fault declared " \
        "by the user program writing its own value to S:6 and setting S:1/13."
    result["classification"] = FAULT_UNCLASSIFIED
    result["action"] = "Check the user program and the user manual for any " \
        "specialty modules in the system for this code."
    return result

def readStatusWord(address):
    # Returns a (value, error) tuple for a single status file word.  The status
    # file is read as a signed integer, so the value is masked back into the
    # unsigned 16 bit word the fault codes are documented as.
    try:
        ret = comm.read(address)
    except Exception as error:
        return (None, str(error))
    if ret == None:
        return (None, "no response from the PLC")
    if ret.error != None:
        return (None, str(ret.error))
    if ret.value == None:
        return (None, "no value returned")
    return (int(ret.value) & 0xFFFF, None)

def printFaultCodeDetail(label, text):
    print("    {0:<16}{1}".format(label,
        ("\n" + " " * 20).join(textwrap.wrap(text, 58))))

def printFaultCode(label, address, value, error, extra_detail):
    # extra_detail is a list of additional lines gathered from the PLC, such as
    # the minor error bits that produced fault code 0020.
    if error != None:
        print("{0} ({1}): unavailable - {2}".format(label, address, error))
        return
    info = describeFaultCode(value)
    detail = info["detail"] + extra_detail
    if (output_format == "minimal"):
        print("{0}=0x{1} {2}{3}".format(address, info["code"],
            info["description"],
            "" if len(detail) == 0 else "  " + " ".join(detail)))
        return
    print("{0} ({1}): 0x{2}  ({3} decimal)".format(label, address,
        info["code"], info["value"]))
    printFaultCodeDetail("Description:", info["description"])
    for line in detail:
        printFaultCodeDetail("Additional:", line)
    if len(info["classification"]) > 0:
        printFaultCodeDetail("Classification:", info["classification"])
    if len(info["action"]) > 0:
        printFaultCodeDetail("Action:", info["action"])

#endregion FAULT CODE HELPER FUNCTIONS

#region CONSOLE COMMAND DEFINITIONS
def closeConnection():
    global comm
    if (comm != None):
        try:
            comm.close()
        except Exception:
            pass
        comm = None
    return

def ipAddress(args):
    # Returns True only when a connection to the PLC was actually opened.
    global comm
    closeConnection()
    try:
        comm = SLCDriver(args)
        comm.open()
    except Exception as error:
        print("ERROR - Unable to connect to {0}.  {1}".format(args,
            getErrorMessage(error)))
        comm = None
        return False
    return True

def getPLCDateTime():
    # The clock/calendar occupies S:37 (year) through S:42 (seconds), so a
    # single multi-element read returns all six words.  Returns a
    # ([yr, mo, dy, hh, mm, ss], error) tuple.
    try:
        ret = comm.read("S:37{6}")
    except Exception as error:
        return (None, getErrorMessage(error))
    if (ret == None):
        return (None, "no response from the PLC")
    if (ret.error != None):
        return (None, str(ret.error))
    if (ret.value == None or len(ret.value) < 6):
        return (None, "the clock/calendar words S:37 through S:42 could not "
                      "be read")
    return (ret.value, None)

def getPLCTime(args):
    if (comm == None):
        print("ERROR - No IPAddress specified.  Use IPAddress command.")
        return
    if (output_format == "raw"):
        print(comm.read('S:37'))
        print(comm.read('S:38'))
        print(comm.read('S:39'))
        print(comm.read('S:40'))
        print(comm.read('S:41'))
        print(comm.read('S:42'))
        return
    values, error = getPLCDateTime()
    if (error != None):
        print("ERROR - Unable to read the PLC time.  {0}".format(error))
        return
    yr, mo, dy, hh, mm, ss = values[0:6]
    if (output_format == "minimal"):
        # Zero padded and sortable, for anything parsing the output.
        print('{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(yr, mo, dy,
            hh, mm, ss))
    else:
        print('{}/{}/{} {}:{:02d}:{:02d}'.format(mo, dy, yr, hh, mm, ss))

def setPLCTime(args):
    if (comm == None):
        print("ERROR - No IPAddress specified.  Use IPAddress command.")
        return
    current_time = datetime.datetime.now()
    yr = current_time.year
    mo = current_time.month
    dy = current_time.day
    hh = current_time.hour
    mm = current_time.minute
    ss = current_time.second
    comm.write(('S:37', yr))
    comm.write(('S:38', mo))
    comm.write(('S:39', dy))
    comm.write(('S:40', hh))
    comm.write(('S:41', mm))
    comm.write(('S:42', ss))
    print('PLC time set to {}/{}/{} {}:{:02d}:{:02d}'.format(mo, dy, yr, hh, mm, ss))

def getFaultCodes(args):
    # Reports the current (S:6) and last (S:54) major error fault codes along
    # with the Rockwell description for each, interpreting any additional
    # information the code carries such as the slot or data file number.
    if (comm == None):
        print("ERROR - No IPAddress specified.  Use IPAddress command.")
        return
    start_time = time.time()
    status, status_error = readStatusWord("S:1")
    current, current_error = readStatusWord("S:6")
    last, last_error = readStatusWord("S:54")
    if last_error != None:
        last_error = "{0} (S:54 is only present on SLC 5/03 and higher " \
                     "processors)".format(last_error)
    # Some codes keep their detail elsewhere in the status file.  Code 0020 only
    # reports that a minor error bit was set at the end of the scan - S:5 says
    # which one.  Code 00A1 on an SLC 5/05 puts an Ethernet daughterboard
    # specific code in S:15.  Both words hold the present state of the
    # processor, so they are only used to expand the current fault code.
    extra_detail = []
    if current == 0x0020:
        minor, minor_error = readStatusWord("S:5")
        if minor_error != None:
            extra_detail.append("S:5 could not be read to identify the minor "
                                "error bit - {0}.".format(minor_error))
        else:
            bits = [MINOR_ERROR_BITS[bit] for bit in sorted(MINOR_ERROR_BITS) \
                if (minor & (1 << bit)) != 0]
            if len(bits) == 0:
                extra_detail.append("No minor error bit is set in S:5 "
                    "(0x{0:04X}) - the bit that caused the fault has already "
                    "been cleared.".format(minor))
            for bit in bits:
                extra_detail.append("Minor error bit set in S:5 - " + bit)
    if current == 0x00A1:
        ethernet, ethernet_error = readStatusWord("S:15")
        if ethernet_error == None:
            extra_detail.append("The Ethernet daughterboard fault code in S:15 "
                "is 0x{0:04X} ({0} decimal).  Refer to the SLC 5/05 "
                "documentation for this code.".format(ethernet))
    exec_time = time.time() - start_time
    if (output_format == "minimal"):
        if status_error == None:
            print("S:1/13={0}".format(1 if (status & 0x2000) != 0 else 0))
        else:
            print("S:1/13=!ERROR!")
    else:
        if status_error != None:
            printFaultCodeDetail("Processor:",
                "the major error halted bit S:1/13 is unavailable - "
                "{0}".format(status_error))
        elif (status & 0x2000) != 0:
            printFaultCodeDetail("Processor:", "the major error halted bit "
                "S:1/13 is SET - the processor is halted on a major fault.")
        else:
            printFaultCodeDetail("Processor:", "the major error halted bit "
                "S:1/13 is clear - the processor is not halted on a major "
                "fault.  S:6 is never cleared by the processor, so a code "
                "below may be left over from a fault that has since been "
                "cleared.")
        print("")
    printFaultCode("Current major error fault code", "S:6", current,
        current_error, extra_detail)
    if (output_format != "minimal"):
        print("")
    printFaultCode("Last major error fault code", "S:54", last, last_error, [])
    if (show_timing):
        print("Executed in {0:7.3f} seconds.".format(exec_time))
    return

def read(args):
    if (comm == None):
        print("ERROR - No IPAddress specified.  Use IPAddress command.")
        return
    start_time = time.time()
    ret = comm.read(args)
    exec_time = time.time() - start_time
    if (output_format == "raw"):
        print(ret)
    elif (output_format == "readable"):
        print(ret.value)
    elif (output_format == "minimal"):
        # One "tag=value" line, the same form the tag file commands produce,
        # so that a script can parse a single read the same way it parses a
        # whole tag file.
        print("{0}={1}".format(args, ret.value))
    if (show_timing):
        print("Executed in {0:7.3f} seconds.".format(exec_time))
    return

def readTagFile(args):
    if (comm == None):
        print("ERROR - No IPAddress specified.  Use IPAddress command.")
        return
    words = args.split()
    filename = words[0]
    start_time = time.time()
    outData = getTagValuesFromFile(filename)
    if len(outData) > 0:
        outFile = ""
        if len(words) > 1:
            outFile = words[1]
        exec_time = time.time() - start_time
        if len(outFile) > 0:
            Path(outFile).write_text("\n".join(outData))
        else:
            print("\n".join(outData))
        if (show_timing):
            print("Executed in {0:7.3f} seconds.".format(exec_time))
    return

def optimizeTagFile(args):
    # This function returns or writes an optimized tag list based on the supplied tag list file.
    words = args.split()
    filename = words[0]
    outFile = ""
    tags = []
    if len(words) > 1:
        outFile = words[1]
    try:
        tags = Path(filename).read_text().split("\n")
    except Exception as error:
        print("ERROR - Error opening the file {0}. {1}".format(filename, str(error)))
        return
    start_time = time.time()
    # Sort the file alphabetically.
    tags.sort()
    outData = []
    # Convert all bit tag formats to word/bit format.
    for tag in tags:
        outData.append(convertToWordBit(tag))
    # Group tags from like files.
    files = []
    for tag in outData:
        if len(tag) > 0:
            file = tag.split(":")[0]
            address = tag.split("/")[0]
            field = address.split(":")[1]
            if field.isnumeric():
                word = int(field)
                foundIndex = foundFile(file, files)
                if foundIndex == NOTFOUND:
                    files.append({"file": file, "start_word": word, "end_word": word})
                else:
                    if files[foundIndex]["start_word"] > word:
                        files[foundIndex]["start_word"] = word
                    if files[foundIndex]["end_word"] < word:
                        files[foundIndex]["end_word"] = word
            else:
                files.append({"file": file, "address": field})
    # Create new tag list from file grouped tags.
    outData = []
    for file in files:
        if "start_word" in file.keys():
            if file["file"].startswith("F"):
                outData += getOptimizedTag(file, 60)     
            elif file["file"].startswith("N") or file["file"].startswith("B"):
                outData += getOptimizedTag(file, 120)     
            else:
                outData.append(file["file"] + ":" + str(file["start_word"]) \
                    + "{" + str(file["end_word"] - file["start_word"] + 1) + "}")
        else:
            outData.append(file["file"] + ":" + file["address"])
    exec_time = time.time() - start_time
    if len(outFile) > 0:
        Path(outFile).write_text("\n".join(outData))
    else:
        print("\n".join(outData))
    if (show_timing):
        print("Executed in {0:7.3f} seconds.".format(exec_time))
    return


def readOptimizedTagFile(args):
    if (comm == None):
        print("ERROR - No IPAddress specified.  Use IPAddress command.")
        return
    words = args.split()
    if len(words) < 2:
        print("ERROR - Invalid number of arguments.  See help for more info.")
        return
    tagfilename = words[0]
    opttagfilename = words[1]
    outFile = ""
    if len(words) > 2:
        outFile = words[2]
    start_time = time.time()
    tagData = getTagValuesFromFile(opttagfilename)
    if len(tagData) > 0:
        # Open the tagfile, loop through the tags and find the value for each in the tagData.
        try:
            tags = Path(tagfilename).read_text().split("\n")
        except Exception as error:
            print("ERROR - Error opening the file {0}. {1}".format(tagfilename, str(error)))
            return
        outData = []
        for tag in tags:
            if len(tag) > 0:
                tagValue = str(getTagValueFromData(tag, tagData))
                outData.append(tag + "=" + tagValue)
        exec_time = time.time() - start_time
        if len(outFile) > 0:
            Path(outFile).write_text("\n".join(outData))
        else:
            print("\n".join(outData))
        if (show_timing):
            print("Executed in {0:7.3f} seconds.".format(exec_time))    
    return

def getWriteValue(tag, value):
    # The value arrives from the command line as text, but pycomm3 packs it
    # according to the data file type and rejects a string outright ("Failed to
    # create a writeable value"), so it has to be converted here first.
    if ("/" in tag):
        # A bit address takes a 1 or a 0.
        state = value.casefold()
        if (state in ["1", "on", "true", "set"]):
            return 1
        if (state in ["0", "off", "false", "clear"]):
            return 0
        raise ValueError("{0} is a bit address, so the value must be 1 or 0, "
                         "not {1}.".format(tag, value))
    if (not isNumber(value)):
        raise ValueError("{0} is not a number.".format(value))
    number = getNumber(value)
    # The floating point files hold a fractional value; every other data file
    # holds an integer, and silently rounding one would write a value the
    # operator did not ask for.
    if (tag.split(":")[0].casefold().startswith("f")):
        return float(number)
    if (float(number) != int(float(number))):
        raise ValueError("{0} holds integers, so {1} cannot be written to "
                         "it.".format(tag, value))
    return int(float(number))

def write(args):
    if (comm == None):
        print("ERROR - No IPAddress specified.  Use IPAddress command.")
        return
    words = args.split()
    if (len(words) < 2):
        print("ERROR - Write requires a tag and a value.  See help for more info.")
        return
    tag = words[0]
    try:
        value = getWriteValue(tag, words[1])
    except ValueError as error:
        print("ERROR - {0}".format(str(error)))
        return
    start_time = time.time()
    try:
        ret = comm.write((tag, value))
    except Exception as error:
        print("ERROR - Unable to write {0} to {1}.  {2}".format(words[1], tag,
            getErrorMessage(error)))
        return
    exec_time = time.time() - start_time
    print(ret)
    if (show_timing):
        print("Executed in {0:7.3f} seconds.".format(exec_time))
    return

def getVersion(args):
    # Returned as well as printed so that the value is available to any caller
    # that imports this module instead of running it from the console.
    print(version)
    return version

def getHelp(args):
    print('''
    Commands: (Not case sensitive.)
        Help                        - Displays this list of commands.
        Version                     - Displays the application version number.
        IPAddress <ip address>      - Sets the IP address for the target PLC.
        Quit                        - Leave console application.
        GetPLCTime                  - Returns the PLC time.
        SetPLCTime                  - Sets the PLC time to the current time.
        GetFaultCodes               - Returns the current (S:6) and last (S:54) major error
                                      fault codes with their descriptions.
        Read <tag>                  - Returns the specified tag's value from the target PLC.
        Write <tag> <value>         - Sets the specified tag's value in the target PLC.
        Output (Raw | Readable | Minimal)
                                    - Sets the output format.  Raw is the default.
        ShowTiming (On | Off)       - Turns on or off the time to execute feedback.
          
    Multi-Tag Commands: (Filenames are case sensitive.)
        ReadTagFile <filename> [<outfile>]
            - Returns the values of the tags from the file.
        OptimizeTagFile <filename> [<outfile>]
            - Returns an optimized tag list from the source file.
        ReadOptimizedTagFile <tagfilename> <optimizedtagfilename> [<outfile>]
            - Returns the values of the tags from the file using the optimized tag list.
    ''')
    return

def output(args):
    global output_format
    if (args in output_formats):
        output_format = args
        print("Output format set to {}".format(args))
    else:
        print("Invalid output format")
    return

def showTiming(args):
    global show_timing
    if (args in ["on", "off"]):
        show_timing = args == "on"
        print("ShowTiming set to " + args + ".")
    else:
        print("Invalid ShowTiming argument.  Valid arguments are 'on' or 'off'.")
    return

#endregion CONSOLE COMMAND DEFINITIONS

#region COMMAND LOOP
def parseCommand(command):
    words = command.casefold().split()
    if (len(words) > 0):
        if (words[0] == "help"):
            getHelp(command)
        elif (words[0] == "version"):
            getVersion(getAdditionalArgs(command))
        elif (words[0] == "ipaddress"):
            if (len(words) > 1):
                ipAddress(words[1])
            else:
                print("ERROR - IPAddress requires an IP address.  See help "
                      "for more info.")
        elif (words[0] == "getplctime"):
            getPLCTime(getAdditionalArgs(command))
        elif (words[0] == "setplctime"):
            setPLCTime(getAdditionalArgs(command))
        elif (words[0] == "getfaultcodes"):
            getFaultCodes(getAdditionalArgs(command))
        elif (words[0] == "read"):
            read(getAdditionalArgs(command))
        elif (words[0] == "readtagfile"):
            readTagFile(getAdditionalArgs(command))
        elif (words[0] == "optimizetagfile"):
            optimizeTagFile(getAdditionalArgs(command))
        elif (words[0] == "readoptimizedtagfile"):
            readOptimizedTagFile(getAdditionalArgs(command))
        elif (words[0] == "write"):
            write(getAdditionalArgs(command))
        elif (words[0] == "output"):
            output(getAdditionalArgs(command))
        elif (words[0] == "showtiming"):
            showTiming(getAdditionalArgs(command))
        else:
            print("ERROR - Unrecognized command.  Enter Help for a list of commands.")
    return

def commandLoop():
    command = input("pycomm3_slc_cli> ")
    while (command.casefold() != "quit"):
        parseCommand(command)
        command = input("pycomm3_slc_cli> ")
    return

#endregion COMMAND LOOP

#region HELPER FUNCTIONS
def isIPAddress(value):
    return len(value.split(".")) == 4

def getAdditionalArgs(command):
    words = command.split()
    if (len(words) > 1):
        return " ".join(words[1:])
    else:
        return ""

#endregion HELPER FUNCTIONS

#region MAIN
def main():
    global comm
    arguments = sys.argv
    if (len(arguments) > 1):
        if (isIPAddress(arguments[1])):
            connected = ipAddress(arguments[1])
            if (len(arguments) > 2):
                if (not connected):
                    sys.exit(1)
                parseCommand(" ".join(arguments[2:]))
                closeConnection()
            else:
                commandLoop()
                closeConnection()
        else:
            parseCommand(" ".join(arguments[1:]))
    else:
        commandLoop()
        closeConnection()
    return

#endregion MAIN

main()
