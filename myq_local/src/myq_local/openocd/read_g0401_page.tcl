# Read one bounded page through the known AP1 flash window. This procedure
# changes and restores volatile AP CSW/TAR registers. It never writes DRW,
# target memory, flash, OTP, reset, halt, unlock, erase, or program commands.
proc word_output {command} {
    set value [string trim [capture $command]]
    if {![regexp {^0x[0-9a-fA-F]{8}$} $value]} {
        error "Non-word response"
    }
    return [expr {$value + 0}]
}

proc read_g0401_page_once {start length} {
    if {$start < 0x08202000 || $start >= 0x08205000 || $length != 4096 || ($start & 4095) != 0} {
        error "Invalid G0401 page bounds"
    }
    set failed [catch {
        init
        set dp [word_output {myq.dap dpreg 0}]
        echo [format "DPIDR 0x%08x" $dp]
        if {$dp != 0x6ba02477} {error "Unexpected DPIDR"}
        set id [word_output {myq.dap apid 1}]
        echo [format "AP1_IDR 0x%08x" $id]
        if {$id != 0x84770001} {error "Unexpected AP1 identity"}
        set cfg [word_output {myq.dap apreg 1 0xf4}]
        if {$cfg != 0} {error "Unsupported MEM-AP configuration"}
        set csw [word_output {myq.dap apreg 1 0x00}]
        set tar [word_output {myq.dap apreg 1 0x04}]
        if {($csw & 0x40) == 0 || ($csw & 0x80) != 0} {
            error "MEM-AP disabled or transfer in progress"
        }
        set newcsw [expr {($csw & ~0x37) | 0x12}]
        myq.dap apreg 1 0x00 $newcsw
        if {[word_output {myq.dap apreg 1 0x00}] != $newcsw} {
            error "CSW readback mismatch"
        }
        for {set n 0} {$n < $length / 4} {incr n} {
            set address [expr {$start + 4 * $n}]
            if {($address & 1023) == 0} {myq.dap apreg 1 0x04 $address}
            set data [word_output {myq.dap apreg 1 0x0c}]
            echo [format "PAGE_WORD 0x%08x 0x%08x" $address $data]
        }
        myq.dap apreg 1 0x04 $tar
        myq.dap apreg 1 0x00 $csw
        echo "PAGE_COMPLETE $start $length;"
    } detail]
    if {$failed} {
        echo "G0401_READ_ERROR"
        shutdown error
    } else {
        shutdown
    }
}
