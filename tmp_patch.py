from pathlib import Path
path = Path('client/campaign_quest_log.html')
text = path.read_text()
start_marker = '      const quest = state.preview.item;'
end_marker = '    const renderQuestCardList ='
start = text.index(start_marker)
end = text.index(end_marker, start)
new_block = """
      const quest = state.preview.item || {};
      const statusValue = (quest.status || 'pending').toLowerCase();
      const assignedTo = Array.isArray(quest.assignedTo) ? quest.assignedTo.join(', ') : quest.assignedTo || 'Unassigned';
      const objectives = Array.isArray(quest.objectives) ? quest.objectives : [];
      const done = objectives.filter((obj) => (obj?.state || '').toLowerCase() === 'succeeded').length;
      const total = objectives.length;
