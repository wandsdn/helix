set datafile separator '\t'
set autoscale
unset log
unset key
#set title 'Congestion Loss CDF of Iterations'
set tmargin 0.3
set bmargin 1.7
set lmargin 4.2
set rmargin 0.5

set terminal svg size 244,400 enhanced background rgb 'white' font ',Linux Libertine O,18'
set output 'attmpls_550.svg'

set grid ytics lc rgb '#bbbbbb' lw 1 lt 0
set grid xtics lc rgb '#bbbbbb' lw 1 lt 0
set ytics 0.1 offset 0.5,0 nomirror
set xtics 4 offset 0,0.5 nomirror

set multiplot
set size 1,0.5

# ----- Top Row -----
set origin 0,0.5
set xlabel 'Loss \\%' offset 0,1.2
set ylabel 'CDF' offset 3.2,0
set xrange [0:18]
set yrange [0.6:1]

plot 'ConLoss/attmpls_550/0.dat' using 2:3 title 'CSPF' w lp ls 1 lw 4 pt 0, \
    'ConLoss/attmpls_550/1.dat' using 2:3 title 'MCF' w lp ls 2 lw 4 pt 0 dt (4,1,4,1) , \
    'ConLoss/attmpls_550/6.dat' using 2:3 title 'Helix' w lp ls 7 lw 4 pt 0 dt (6,3,2,3)

# ----- Bottom Row ----
set origin 0,0
set xlabel '\\# Path Changes' offset 0,1.2
set xrange [0:1200]
set yrange [0:1]
set xtics 0,400,800 offset 0,0.5 nomirror
set xtics add ("1200     " 1200 0)
set ytics 0.2 offset 0.5,0 nomirror
plot 'PathChurn/attmpls_550/0.dat' using 2:3 title 'CSPF' w lp ls 1 lw 4 pt 0, \
    'PathChurn/attmpls_550/1.dat' using 2:3 title 'MCF' w lp ls 2 lw 4 pt 0 dt (4,1,4,1) , \
    'PathChurn/attmpls_550/6.dat' using 2:3 title 'Helix' w lp ls 7 lw 4 pt 0 dt (6,3,2,3)

unset multiplot
