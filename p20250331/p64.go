package p20250331

func minPathSum(grid [][]int) int {
	m := len(grid)
	if m == 0 {
		return 0
	}
	n := len(grid[0])
	for mi := range m {
		for ni := range n {
			if mi == 0 && ni != 0 {
				grid[mi][ni] += grid[mi][ni-1]
			} else if mi != 0 && ni == 0 {
				grid[mi][ni] += grid[mi-1][ni]
			} else if mi != 0 && ni != 0 {
				grid[mi][ni] = min(grid[mi][ni]+grid[mi][ni-1], grid[mi][ni]+grid[mi-1][ni])
			}
		}
	}
	return grid[m-1][n-1]
}
