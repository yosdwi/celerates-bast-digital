package main

import "os"

func (b *bridge) cleanupExport(path string) {
	if path == "" {
		return
	}
	if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
		b.state.logf("export cleanup failed for %s: %v", path, err)
	}
}
