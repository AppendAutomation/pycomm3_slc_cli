# pycomm3_slc_cli

The pycomm3_slc_cli application is intended to encapsulate many of the pycomm3 commands, using the SLCDriver, into a single directly executable program.  Using pyinstaller, pycomm3_slc_cli is packaged into an .exe file that can be run on any Windows computer without the need for installing Python.  This can be particularly
handy for systems where an end-user does not have the Rockwell software, but needs to update a value, set the time on the controller or read or write settings from or to the target PLC.

Warning!  PLCs control industrial equipment and writing values to a PLC that is actively operating equipment should be done with great care and is at your own risk.

Execution of the application will take the form of a single command or a shell console application allowing multiple commands to be executed.

## Download
The latest release is **[v0.3.0](https://github.com/AppendAutomation/pycomm3_slc_cli/releases/tag/v0.3.0)** - download [pycomm3_slc_cli.exe](https://github.com/AppendAutomation/pycomm3_slc_cli/releases/download/v0.3.0/pycomm3_slc_cli.exe) and run it, no installation required.  All releases are listed on the [releases page](https://github.com/AppendAutomation/pycomm3_slc_cli/releases).

The executable is built with PyInstaller against Python 3.8.10 on Windows 7 SP1 - the last Python release with official Windows 7 support - so it runs on Windows 7 and newer.  It is a 64-bit executable and will not run on 32-bit Windows.

## Examples of Usage
Single command syntax example:
```
pycomm3_slc_cli 192.168.1.10 Read N9:0
n9:0, 21229, N, None
```

Console app example:
```
pycomm3_slc_cli 192.168.1.10
pycomm3_slc_cli> Read N9:1
n9:1, 314, N, None
pycomm3_slc_cli> quit
```

OR
```
pycomm3_slc_cli
pycomm3_slc_cli> Read N9:2
ERROR - No IPAddress specified.  Use IPAddress command.
pycomm3_slc_cli> IPAddress 192.168.1.10
pycomm3_slc_cli> Read N9:2
n9:2, 12, N, None
pycomm3_slc_cli> quit
```

Read an array:
```
pycomm3_slc_cli 192.168.1.10 Read N9:0{5}
n9:0, [1, 2, 3, 4, 5], N, None
```

Get the current and last fault code with their descriptions:
```
pycomm3_slc_cli 100.100.100.50 GetFaultCodes
    Processor:      the major error halted bit S:1/13 is SET - the processor
                    is halted on a major fault.

Current major error fault code (S:6): 0x0A52  (2642 decimal)
    Description:    A module required for the user program is detected as
                    missing or removed.
    Additional:     The high byte 0x0A identifies slot 10.
    Classification: Recoverable user fault - the user fault routine may clear
                    the fault by clearing S:1/13.
    Action:         Either disable the slot in the status file (S:11 and
                    S:12), or insert the required module in the slot.

Last major error fault code (S:54): 0x0020  (32 decimal)
    Description:    A minor error bit is set at the end of the scan.  Refer to
                    the S:5 minor error bits (lower byte only).
    ...
```

```S:6``` holds the fault code for the current or most recent major error and
```S:54``` mirrors the last code stored in S:6 (SLC 5/03 and higher processors
only).  The processor never clears S:6, so ```GetFaultCodes``` also reports the
major error halted bit ```S:1/13``` to show whether the processor is actually
halted on the code it reports.  Codes that carry additional information in their
high byte - the slot number for the I/O errors, or the data file number for
code xx39 - are interpreted as part of the description.  When the current code
is ```0020``` the minor error bits in ```S:5``` are read and reported, and when
it is ```00A1``` on an SLC 5/05 the Ethernet daughterboard code in ```S:15``` is
reported.

The descriptions come from the Allen-Bradley SLC 500 Instruction Set Reference
Manual, publication 1747-RM001G-EN-P (November 2008) - chapter 16
"Troubleshooting Faults" and appendix B "SLC Status File".

Use ```Output minimal``` for a one line per code form:
```
pycomm3_slc_cli> Output minimal
Output format set to minimal
pycomm3_slc_cli> GetFaultCodes
S:1/13=1
S:6=0x0A52 A module required for the user program is detected as missing or removed.  The high byte 0x0A identifies slot 10.
S:54=0x0020 A minor error bit is set at the end of the scan.  Refer to the S:5 minor error bits (lower byte only).
```



## Commands
The following commands are not case-sensitive.
+ ```Help```                        - Displays this list of commands.
+ ```IPAddress <ip address>```      - Sets the IP address for the target PLC.
+ ```Quit```                        - Leave console application.
+ ```GetPLCTime```                  - Returns the PLC time.
+ ```SetPLCTime```                  - Sets the PLC time to the current time.
+ ```GetFaultCodes```               - Returns the current (S:6) and last (S:54) major error fault codes with their descriptions.
+ ```Read <tag>```                  - Returns the specified tag's value from the target PLC.
+ ```Write <tag> <value>```         - Sets the specified tag's value in the target PLC.
+ ```Output (Raw | Readable)```     - Sets the output format.  Raw is the default.
+ ```ShowTiming (On | Off)```      - Turns on or off the time to execute feedback.
          
### Multi-Tag Commands:
Filenames are case sensitive.
+ ```ReadTagFile <filename> [<outfile>]```
    - Returns the values of the tags from the file.
+ ```OptimizeTagFile <filename> [<outfile>]```
    - Returns an optimized tag list from the source file.
+ ```ReadOptimizedTagFile <tagfilename> <optimizedtagfilename> [<outfile>]```
    - Returns the values of the tags from the tagfile using the optimizedtagfile to retrieve the values.

## The pycomm3 Project
This application is a command line wrapper to ease the use of the many functions of the pycomm3 library.  The pyinstaller program is used to create an executable package on Windows that does not require the installation of Python.

For more information and documentation:
https://github.com/ottowayi/pycomm3

**Special thanks to ruscito, ottowayi and all the contributors that make pycomm3 possible.**

## Development Environment
In order to build the executable using pyinstaller, first clone this repository and then install both pycomm3 and pyinstaller using pip.

```
git clone https://github.com/AppendAutomation/pycomm3_slc_cli.git
cd pycomm3_slc_cli
pip install pycomm3
pip install pyinstaller
```

### Building the Executable
In order to build the executable for the Windows platform it is necessary to run pyinstaller on a Windows computer.  Keep in mind that Python 3.9+ cannot run on Windows 7.  For this reason it is recommended that a Windows 7 system with Python installed be used to create the executable in order to ensure compatability with Windows 7 and newer versions of Windows.
 
```
pyinstaller -F pycomm3_slc_cli.py
```

## License

This project is licensed under the MIT License.
