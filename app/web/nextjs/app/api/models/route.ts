import { NextResponse } from 'next/server';

export async function GET() {
  try {
    // Fetch available models from the backend
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/llm/models`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error('Failed to fetch models');
    }

    const models = await response.json();
    
    // Transform models for UI consumption
    const formattedModels = models.map((model: any) => ({
      id: model.id,
      name: model.name,
      provider: model.provider,
      max_tokens: model.max_tokens,
      cost_per_1k_input: model.cost_per_1k_input || 0,
      cost_per_1k_output: model.cost_per_1k_output || 0,
      description: model.description || '',
      category: model.category || 'general',
    }));

    return NextResponse.json(formattedModels);
  } catch (error) {
    console.error('Error fetching models:', error);
    return NextResponse.json(
      { error: 'Failed to fetch models' },
      { status: 500 }
    );
  }
}