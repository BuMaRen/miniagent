package p20250331

import (
	"fmt"
	"testing"
)

func TestP64(t *testing.T) {
	fmt.Println(minPathSum([][]int{
		{1, 3, 1},
		{1, 5, 1},
		{4, 2, 1},
	}))
}
