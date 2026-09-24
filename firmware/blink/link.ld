/* STM32WB55RG, Cortex-M4 side. Only the bottom of flash is used; the top
   holds ST's wireless stack for the M0+ core and must not be touched. */
ENTRY(Reset_Handler)

MEMORY
{
  FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 512K
  RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 64K
}

_estack = ORIGIN(RAM) + LENGTH(RAM);

SECTIONS
{
  .isr_vector : { KEEP(*(.isr_vector)) } > FLASH
  .text       : { *(.text*) *(.rodata*) . = ALIGN(4); } > FLASH

  _sidata = LOADADDR(.data);
  .data : { _sdata = .; *(.data*) . = ALIGN(4); _edata = .; } > RAM AT > FLASH
  .bss  : { _sbss = .;  *(.bss*) *(COMMON) . = ALIGN(4); _ebss = .; } > RAM
}
