import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts';
import { useChatStore } from '../../stores/treeStore';
import { useMemo, useState } from 'react';

const ARCHETYPES = [
  'Builder', 'Analyst', 'Guardian', 'Caregiver',
  'Creator', 'Operator', 'Scientist', 'Strategist'
];

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16'];

export default function PersonaPanel() {
  const { inspectorTab } = useChatStore();
  const [persona, setPersona] = useState(null);
  const [blend, setBlend] = useState<Record<string, number>>({});

  const data = useMemo(() => {
    return ARCHETYPES.map((archetype, index) => ({
      name: archetype,
      value: blend[archetype] || 0,
      color: COLORS[index],
    }));
  }, [blend]);

  return (
    <div className={inspectorTab !== 'persona' ? 'hidden' : ''}>
      <h3 className="font-semibold mb-4">Persona Configuration</h3>
      <div className="h-64 w-full">
        <ResponsiveContainer>
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              innerRadius={60}
              outerRadius={90}
              dataKey="value"
            >
              {data.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.color} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="space-y-3 mt-4">
        {ARCHETYPES.map((archetype) => (
          <div key={archetype} className="space-y-1">
            <div className="flex justify-between text-sm">
              <span>{archetype}</span>
              <span>{((blend[archetype] || 0) * 100).toFixed(0)}%</span>
            </div>
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={blend[archetype] || 0}
              onChange={(e) => setBlend({
                ...blend,
                [archetype]: parseFloat(e.target.value),
              })}
              className="w-full h-2 bg-secondary rounded-lg appearance-none"
            />
          </div>
        ))}
      </div>
    </div>
  );
}