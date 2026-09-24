# Build and flash the force-plate firmware.
#
#   .\build.ps1          # compile only
#   .\build.ps1 -Flash   # compile, then flash the connected NUCLEO-WB55RG
#
# Uses the compiler and programmer bundled with STM32CubeIDE - no separate
# toolchain install, and no CubeMX project needed.
param([switch]$Flash)

$ErrorActionPreference = "Stop"

$ide = "C:\ST\STM32CubeIDE_2.2.0\STM32CubeIDE\plugins"
$gcc = Get-ChildItem $ide -Directory | Where-Object { $_.Name -like "*gnu-tools-for-stm32*" } | Select-Object -First 1
$prog = Get-ChildItem $ide -Directory | Where-Object { $_.Name -like "*cubeprogrammer*" } | Select-Object -First 1
if (-not $gcc -or -not $prog) { throw "STM32CubeIDE tools not found under $ide" }

$env:PATH = "$($gcc.FullName)\tools\bin;$env:PATH"
$cli = "$($prog.FullName)\tools\bin\STM32_Programmer_CLI.exe"

Push-Location $PSScriptRoot
try {
    arm-none-eabi-gcc -mcpu=cortex-m4 -mthumb -Os -g -Wall -Wextra -ffreestanding `
        -fno-tree-loop-distribute-patterns -nostdlib -T link.ld main.c startup.c -o fdc.elf
    if ($LASTEXITCODE -ne 0) { throw "compile failed" }
    arm-none-eabi-size fdc.elf

    if ($Flash) { & $cli -c port=SWD -w fdc.elf -v -rst }
}
finally { Pop-Location }
